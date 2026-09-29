# Installation

narratty needs Python 3.12 or newer.

```bash
uv tool install narratty
# or
pipx install narratty
```

## Runtimes

narratty runs the recording pipeline either **natively** (tools on your `PATH`) or
**sandboxed** in a container. By default (`--runtime auto`) it uses Docker when it is
installed, then Podman, and falls back to native mode with a warning.

| Runtime | You need |
|---|---|
| `docker` / `podman` | Docker or Podman |
| `native` | `vhs`, `ttyd`, `ffmpeg` (with `ffprobe`), `git`; Piper is installed with narratty |

Run `narratty doctor` to see what your runtime needs and what is missing. Pick a
runtime with `--runtime` or the `NARRATTY_RUNTIME` environment variable.

!!! note "macOS"
    macOS support is best effort. Native mode works when the tools above are installed
    with Homebrew; sandboxed mode works through Docker Desktop or Podman.
