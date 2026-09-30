# narratty

Turn a YAML script into a narrated terminal video. narratty types your commands in a
real terminal (VHS), speaks the narration with local text-to-speech (Kokoro or Piper)
and keeps voice and picture in sync. It runs sandboxed in Docker or Podman, or
natively.

## Features

- **Spec to video:** a `.narratty.yaml` file becomes an MP4, or an asciicast with
  narration and a player page (`--format cast`).
- **[Local voices](user-guide/voices.md):** Kokoro (natural sounding, the default) or Piper
  (many languages), no cloud service. Narration and typing stay in sync, and audio is
  cached.
- **[Sandboxed by default](user-guide/container.md):** runs in Docker or Podman with no network unless the spec
  asks for it and you approve. The demo runs in a throwaway snapshot of your
  repository. Native mode is available too.
- **Scripting:** hidden setup scenes, waits for screen output, key presses and
  per-scene typing speed.
- **[Demo toolkit](user-guide/toolkit.md):** bat, eza, fd, ripgrep, jq, yazi, tmux and
  zsh as static binaries, for the narratty image and, with one `COPY` line, for any
  dev container.
- **Editor support:** a JSON Schema for completion and inline errors, `validate` with
  line numbers, and shell completion.

## Quick start

```bash
uv tool install narratty            # or: pipx install narratty
narratty init                       # writes demo.narratty.yaml
narratty validate demo.narratty.yaml
narratty build demo.narratty.yaml   # writes demo.mp4
```

A minimal spec:

```yaml
scenes:
  - id: intro
    narration: This is a quick tour of the repository layout.
    actions:
      - type_command: "ls -la"
      - enter
```

Each scene lasts as long as its actions or its narration, whichever is longer. See
[Building a video](user-guide/building.md) for how timing works and the
[spec reference](user-guide/spec.md) for every key.

## Where it runs

| Runtime | Needs | Chosen when |
|---|---|---|
| `docker` / `podman` | the container runtime | installed (default) |
| `native` | `vhs`, `ttyd`, `ffmpeg`, `git` | no container runtime, or `--runtime native` |

`narratty doctor` checks what the selected runtime needs.
