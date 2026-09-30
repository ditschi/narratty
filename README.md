# narratty

Turn a YAML script into a narrated terminal video. narratty types your commands in a
real terminal ([VHS](https://github.com/charmbracelet/vhs)), speaks the narration with
local text-to-speech ([Piper](https://github.com/OHF-Voice/piper1-gpl) or
[Kokoro](https://github.com/thewh1teagle/kokoro-onnx)) and keeps voice and picture in
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
```

With Docker or Podman installed, the build runs in the `ghcr.io/ditschi/narratty`
image and needs nothing else on the host. Without one, `narratty doctor` lists the
tools native mode needs.

**Documentation:** <https://ditschi.github.io/narratty/>

## Development

```bash
uv sync --extra dev
uv run pre-commit install
nox                                 # all quality gates (NOX_CI=1 skips auto-formatting)
```

See the [contributor guide](docs/contributor-guide/dev-setup.md).

## License

[MIT](LICENSE)
