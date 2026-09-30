<p align="center">
  <img src="https://raw.githubusercontent.com/ditschi/narratty/main/docs/assets/logo.svg" alt="narratty" width="320">
</p>

# narratty

Turn a YAML script into a narrated terminal video. narratty types your commands in a
real terminal ([VHS](https://github.com/charmbracelet/vhs)), speaks the narration with
local text-to-speech ([Kokoro](https://github.com/thewh1teagle/kokoro-onnx) or
[Piper](https://github.com/OHF-Voice/piper1-gpl)) and keeps voice and picture in
sync. It runs sandboxed in Docker or Podman, or natively.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

```yaml
# demo.narratty.yaml
scenes:
  - id: intro
    narration: This is a quick tour of the repository layout.
    actions:
      - type_command: "eza --tree --level=1 ."
      - enter
```

```bash
uv tool install narratty            # or: pipx install narratty
narratty build demo.narratty.yaml   # writes demo.mp4
narratty build demo.narratty.yaml -f cast  # demo.cast + demo.mp3 + demo.html
```

With Docker or Podman installed, the build runs in the `ghcr.io/ditschi/narratty`
image and needs nothing else on the host. Without one, `narratty doctor` lists the
tools native mode needs.

**Documentation:** <https://ditschi.github.io/narratty/>

## Features

- **Spec to video:** a `.narratty.yaml` file becomes an MP4, or an asciicast with
  narration and a player page (`--format cast`).
- **Local voices:** Kokoro (natural sounding, the default) or Piper
  (many languages), no cloud service. Narration and typing stay in sync, and audio is
  cached.
- **Sandboxed by default:** runs in Docker or Podman with no network unless the spec
  asks for it and you approve. The demo runs in a throwaway snapshot of your
  repository. Native mode is available too.
- **Scripting:** hidden setup scenes, waits for screen output, key presses and
  per-scene typing speed.
- **Editor layout:** a file explorer with preview above the shell
  (`terminal.layout: editor`), `focus` and `reveal` actions, and a `diff` of what the
  demo changed.
- **Demo toolkit:** bat, delta, eza, fd, ripgrep, jq, micro, yazi, tmux and zsh as
  static binaries, for the narratty image and, with one `COPY` line, for any dev
  container.
- **Editor support:** a JSON Schema for completion and inline errors, `validate` with
  line numbers, and shell completion.

## Development

```bash
uv sync --extra dev
uv run pre-commit install
nox                                 # all quality gates (NOX_CI=1 skips auto-formatting)
```

See the [contributor guide](docs/contributor-guide/dev-setup.md).

## License

[MIT](LICENSE)
