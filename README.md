# narratty

Turn a YAML script into a narrated terminal video: scripted shell sessions rendered with
[VHS](https://github.com/charmbracelet/vhs), voiceover from local text-to-speech
([Piper](https://github.com/OHF-Voice/piper1-gpl) or [Kokoro](https://github.com/thewh1teagle/kokoro-onnx)),
and automatic audio sync. Runs natively or sandboxed in Docker or Podman.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Early development.** Today narratty ships the CLI skeleton, `narratty doctor` and shell
> completion. The [design](docs/design.md) describes the full pipeline and the milestones.

## How it will work

```yaml
# demo.narratty.yaml
tts: { provider: piper, voice: en_US-lessac-medium }
scenes:
  - id: intro
    narration: This is a quick tour of the repository layout.
    actions:
      - type_command: "eza --tree --level=1 ."
      - enter
```

```bash
narratty build demo.narratty.yaml -o demo.mp4
```

Each scene's narration is synthesized locally, measured, and the terminal session is timed
so the voice and the picture stay in sync.

## Install

```bash
uv tool install narratty      # or: pipx install narratty
narratty --install-completion # bash, zsh, fish, PowerShell
narratty doctor               # what does my runtime need?
```

`--runtime auto` (the default) renders in Docker or Podman when available and falls back to
native mode otherwise. Override with `--runtime` or `NARRATTY_RUNTIME`.

## Development

```bash
uv sync --extra dev
uv run pre-commit install
nox                           # all quality gates (NOX_CI=1 skips auto-formatting)
```

See [docs/contributor-guide](docs/contributor-guide/dev-setup.md) for the full list of
sessions and the release process.

## License

[MIT](LICENSE)
