package main

import (
	"bufio"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

func serve(socket, workdir string) error {
	abstract := strings.HasPrefix(socket, "@")
	if !abstract {
		_ = os.Remove(socket)
	}
	listener, err := net.Listen("unix", socket)
	if err != nil {
		return err
	}
	if !abstract {
		// The recorder runs as another user in another container.
		if err := os.Chmod(socket, 0o777); err != nil {
			return err
		}
	}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		<-stop
		listener.Close()
	}()
	for {
		conn, err := listener.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		go handle(conn, workdir)
	}
}

func mergeEnv(base []string, overrides map[string]string) []string {
	env := make([]string, 0, len(base)+len(overrides))
	for _, entry := range base {
		name, _, _ := strings.Cut(entry, "=")
		if _, replaced := overrides[name]; !replaced {
			env = append(env, entry)
		}
	}
	for name, value := range overrides {
		env = append(env, name+"="+value)
	}
	return env
}

func handle(conn net.Conn, workdir string) {
	defer conn.Close()
	reader := bufio.NewReader(conn)
	out := &frameWriter{w: conn}
	h, err := readHeader(reader)
	if err != nil {
		_ = out.write(frameError, []byte(err.Error()))
		return
	}
	if h.Ping {
		_ = out.exit(0)
		return
	}
	if len(h.Argv) == 0 {
		_ = out.write(frameError, []byte("no command given"))
		return
	}
	master, slave, err := openPTY()
	if err != nil {
		_ = out.write(frameError, []byte(err.Error()))
		return
	}
	defer master.Close()
	_ = setSize(master, h.Rows, h.Cols)
	cmd := exec.Command(h.Argv[0], h.Argv[1:]...)
	cmd.Env = mergeEnv(os.Environ(), h.Env)
	cmd.Dir = workdir
	if h.Cwd != "" {
		cmd.Dir = h.Cwd
	}
	cmd.Stdin, cmd.Stdout, cmd.Stderr = slave, slave, slave
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true, Setctty: true, Ctty: 0}
	err = cmd.Start()
	slave.Close()
	if err != nil {
		_ = out.write(frameError, []byte(fmt.Sprintf("cannot start %s: %v", h.Argv[0], err)))
		return
	}
	pid := cmd.Process.Pid

	go func() { // client → shell
		for {
			kind, payload, err := readFrame(reader)
			if err != nil { // the client went away: hang up like a closed terminal
				_ = syscall.Kill(-pid, syscall.SIGHUP)
				return
			}
			switch kind {
			case frameInput:
				_, _ = master.Write(payload)
			case frameResize:
				if rows, cols, ok := decodeResize(payload); ok {
					_ = setSize(master, rows, cols)
				}
			}
		}
	}()

	drained := make(chan struct{})
	go func() { // shell → client
		defer close(drained)
		buf := make([]byte, 32*1024)
		for {
			n, err := master.Read(buf)
			if n > 0 {
				if out.write(frameOutput, buf[:n]) != nil {
					return
				}
			}
			if err != nil { // EIO once every process has closed the terminal
				return
			}
		}
	}()

	_ = cmd.Wait()
	// Background jobs may keep the terminal open; do not wait for them for long.
	select {
	case <-drained:
	case <-time.After(300 * time.Millisecond):
		_ = master.SetReadDeadline(time.Now())
		<-drained
	}
	_ = out.exit(exitCode(cmd.ProcessState))
}

func exitCode(state *os.ProcessState) int {
	if status, ok := state.Sys().(syscall.WaitStatus); ok && status.Signaled() {
		return 128 + int(status.Signal())
	}
	return state.ExitCode()
}

func pingOnce(socket string) error {
	conn, err := net.DialTimeout("unix", socket, time.Second)
	if err != nil {
		return err
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(2 * time.Second))
	if err := writeHeader(conn, header{Ping: true}); err != nil {
		return err
	}
	kind, payload, err := readFrame(conn)
	if err != nil {
		return err
	}
	if kind != frameExit || decodeExit(payload) != 0 {
		return errors.New("unexpected answer")
	}
	return nil
}
