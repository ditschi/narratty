# narratty

Turn a YAML script into a narrated terminal video: scripted shell sessions rendered with
[VHS](https://github.com/charmbracelet/vhs), voiceover from local text-to-speech (Piper or
Kokoro), and automatic audio sync. Runs natively or sandboxed in Docker or Podman.

!!! warning "Early development"
    narratty is being built milestone by milestone. Today it ships the CLI skeleton,
    `narratty doctor` and shell completion. The [design](design.md) describes where it
    is going.

## Quick look

```bash
uv tool install narratty        # or: pipx install narratty
narratty --install-completion   # bash, zsh, fish or PowerShell
narratty doctor                 # which tools does my runtime need?
```
