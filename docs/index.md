# narratty

Turn a YAML script into a narrated terminal video. narratty types your commands in a
real terminal (VHS), speaks the narration with local text-to-speech (Piper or Kokoro)
and keeps voice and picture in sync. It runs sandboxed in Docker or Podman, or
natively.

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
