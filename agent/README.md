# narratty-agent

Runs the demo shell inside a [project environment](../docs/user-guide/environments.md).
Static Go, no dependencies outside the standard library, Linux only.

| Command | Does |
|---|---|
| `serve --socket PATH [--workdir DIR]` | Listen on a Unix socket; start one shell per connection in a pseudo-terminal |
| `connect --socket PATH [--env NAME] -- ARGV` | Run `ARGV` through the agent, attached to this terminal; exits with its code |
| `ping --socket PATH [--wait 10s]` | Check the agent answers |

A socket starting with `@` is an abstract socket.

Protocol: the client sends one JSON line (`argv`, `env`, `cwd`, `rows`, `cols`), then
both sides exchange frames of a type byte, a big-endian `uint32` length and the payload:
`i` input and `r` resize from the client, `o` output, `x` exit code and `e` error from
the agent. `TERM`, `COLORTERM` and the locale variables are forwarded by default.

```bash
nox -s agent                                     # go vet + go test
CGO_ENABLED=0 go build -o narratty-agent .       # a local build
```

The Dockerfile builds it for amd64 and arm64 into `/opt/narratty/agent/<arch>/`.
To try a local build without an image, set `NARRATTY_AGENT_DIR` to a directory with
`<arch>/narratty-agent`.
