package main

import (
	"bufio"
	"net"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

func startServer(t *testing.T) string {
	t.Helper()
	socket := filepath.Join(t.TempDir(), "agent.sock")
	go func() { _ = serve(socket, t.TempDir()) }()
	if err := ping(socket, 5*time.Second); err != nil {
		t.Fatal(err)
	}
	return socket
}

// session runs argv through the agent, sends input, and returns output and exit code.
func session(t *testing.T, socket string, h header, input string) (string, int) {
	t.Helper()
	conn, err := net.Dial("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(10 * time.Second))
	if err := writeHeader(conn, h); err != nil {
		t.Fatal(err)
	}
	out := &frameWriter{w: conn}
	if input != "" {
		_ = out.write(frameInput, []byte(input))
	}
	reader := bufio.NewReader(conn)
	var output strings.Builder
	for {
		kind, payload, err := readFrame(reader)
		if err != nil {
			t.Fatalf("after %q: %v", output.String(), err)
		}
		switch kind {
		case frameOutput:
			output.Write(payload)
		case frameExit:
			return output.String(), decodeExit(payload)
		case frameError:
			return string(payload), -1
		}
	}
}

func TestRunsCommandInTerminal(t *testing.T) {
	socket := startServer(t)
	output, code := session(t, socket, header{
		Argv: []string{"sh", "-c", `test -t 0 && echo tty; stty size; echo "$GREETING"; exit 3`},
		Env:  map[string]string{"GREETING": "hello"},
		Rows: 12, Cols: 34,
	}, "")
	if code != 3 {
		t.Errorf("exit code %d, output %q", code, output)
	}
	for _, want := range []string{"tty", "12 34", "hello"} {
		if !strings.Contains(output, want) {
			t.Errorf("output %q lacks %q", output, want)
		}
	}
}

func TestForwardsInput(t *testing.T) {
	socket := startServer(t)
	output, code := session(t, socket, header{Argv: []string{"sh"}}, "echo typed-$((40+2))\rexit\r")
	if code != 0 || !strings.Contains(output, "typed-42") {
		t.Errorf("exit code %d, output %q", code, output)
	}
}

func TestReportsMissingCommand(t *testing.T) {
	socket := startServer(t)
	output, code := session(t, socket, header{Argv: []string{"no-such-shell"}}, "")
	if code != -1 || !strings.Contains(output, "cannot start no-such-shell") {
		t.Errorf("exit code %d, output %q", code, output)
	}
}

func TestAbstractSocket(t *testing.T) {
	socket := "@narratty-agent-test-" + strings.ReplaceAll(t.Name(), "/", "-")
	go func() { _ = serve(socket, "") }()
	if err := ping(socket, 5*time.Second); err != nil {
		t.Fatal(err)
	}
}

func TestMergeEnv(t *testing.T) {
	env := mergeEnv([]string{"A=1", "B=2"}, map[string]string{"B": "3", "C": "4"})
	slices.Sort(env)
	if !slices.Equal(env, []string{"A=1", "B=3", "C=4"}) {
		t.Errorf("got %v", env)
	}
}
