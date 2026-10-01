// narratty-agent runs the demo shell of a narratty recording inside a project's own
// container. `serve` listens on a Unix socket in that container and starts one
// shell per connection in a pseudo-terminal; `connect` is the client narratty's
// recorder runs instead of the shell. It is statically linked, so it runs in any
// Linux image.
//
//	narratty-agent serve --socket /.narratty/run/agent.sock [--workdir DIR] [--once]
//	narratty-agent connect --socket PATH [--env NAME]... -- bash --norc
//	narratty-agent ping --socket PATH [--wait 10s]
//
// A socket starting with "@" is an abstract socket (no file; shared by everything
// in the same network namespace).
package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"time"
)

var version = "dev"

func main() {
	os.Exit(run(os.Args[1:]))
}

type stringList []string

func (s *stringList) String() string     { return strings.Join(*s, ",") }
func (s *stringList) Set(v string) error { *s = append(*s, v); return nil }

func usage() int {
	fmt.Fprintln(os.Stderr, "usage: narratty-agent serve|connect|ping|version [flags]")
	return 2
}

func run(args []string) int {
	if len(args) == 0 {
		return usage()
	}
	command, args := args[0], args[1:]
	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	socket := flags.String("socket", "", "Unix socket path, or @name for an abstract socket")
	switch command {
	case "serve":
		workdir := flags.String("workdir", "", "start shells in this directory")
		once := flags.Bool("once", false, "exit when the first shell has ended")
		if flags.Parse(args) != nil || *socket == "" {
			return usage()
		}
		if err := serve(*socket, *workdir, *once); err != nil {
			fmt.Fprintln(os.Stderr, "narratty-agent:", err)
			return 1
		}
		return 0
	case "connect":
		var env stringList
		flags.Var(&env, "env", "also forward this environment variable (repeatable)")
		cwd := flags.String("cwd", "", "start the shell in this directory")
		if flags.Parse(args) != nil || *socket == "" || flags.NArg() == 0 {
			return usage()
		}
		code, err := connect(*socket, flags.Args(), append(defaultForward(), env...), *cwd)
		if err != nil {
			fmt.Fprintln(os.Stderr, "narratty-agent:", err)
			return 1
		}
		return code
	case "ping":
		wait := flags.Duration("wait", 0, "keep trying this long")
		if flags.Parse(args) != nil || *socket == "" {
			return usage()
		}
		if err := ping(*socket, *wait); err != nil {
			fmt.Fprintln(os.Stderr, "narratty-agent:", err)
			return 1
		}
		return 0
	case "version":
		fmt.Println(version)
		return 0
	}
	return usage()
}

// defaultForward lists the client variables every shell gets: the terminal type
// and the locale, which describe the client's terminal, not the container.
func defaultForward() []string {
	return []string{"TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE"}
}

func ping(socket string, wait time.Duration) error {
	deadline := time.Now().Add(wait)
	for {
		err := pingOnce(socket)
		if err == nil || time.Now().After(deadline) {
			return err
		}
		time.Sleep(100 * time.Millisecond)
	}
}
