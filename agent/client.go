package main

import (
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"strconv"
	"syscall"
)

func connect(socket string, argv, forward []string, cwd string) (int, error) {
	conn, err := net.Dial("unix", socket)
	if err != nil {
		return 1, err
	}
	defer conn.Close()
	h := header{Argv: argv, Env: map[string]string{}, Cwd: cwd}
	for _, name := range forward {
		if value, ok := os.LookupEnv(name); ok {
			h.Env[name] = value
		}
	}
	stdin := os.Stdin.Fd()
	tty := isTerminal(stdin)
	if tty {
		h.Rows, h.Cols, _ = getSize(stdin)
	} else {
		h.Rows, h.Cols = envSize("LINES"), envSize("COLUMNS")
	}
	if err := writeHeader(conn, h); err != nil {
		return 1, err
	}
	out := &frameWriter{w: conn}
	if tty {
		restore, err := makeRaw(stdin)
		if err == nil {
			defer restore()
		}
		resized := make(chan os.Signal, 1)
		signal.Notify(resized, syscall.SIGWINCH)
		defer signal.Stop(resized)
		go func() {
			for range resized {
				if rows, cols, err := getSize(stdin); err == nil {
					_ = out.resize(rows, cols)
				}
			}
		}()
	}
	go func() { // keystrokes → shell
		buf := make([]byte, 4096)
		for {
			n, err := os.Stdin.Read(buf)
			if n > 0 && out.write(frameInput, buf[:n]) != nil {
				return
			}
			if err != nil {
				return
			}
		}
	}()
	for {
		kind, payload, err := readFrame(conn)
		if err != nil {
			if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
				return 1, errors.New("the agent closed the connection")
			}
			return 1, err
		}
		switch kind {
		case frameOutput:
			if _, err := os.Stdout.Write(payload); err != nil {
				return 1, err
			}
		case frameExit:
			return decodeExit(payload), nil
		case frameError:
			return 1, fmt.Errorf("%s", payload)
		}
	}
}

func envSize(name string) uint16 {
	value, err := strconv.ParseUint(os.Getenv(name), 10, 16)
	if err != nil {
		return 0
	}
	return uint16(value)
}
