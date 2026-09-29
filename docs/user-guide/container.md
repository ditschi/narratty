# Sandboxed runs

With Docker or Podman installed, `build`, `render`, `tts`, `plan` and `tape` run
inside the narratty image by default (`--runtime auto`). The image contains VHS,
ttyd, Chromium, ffmpeg, fonts, Piper and a few popular CLIs (`git`, `bat`, `eza`,
`fd`, `ripgrep`, `jq`, `tree`). You only need narratty itself and a container
runtime on the host.

```bash
narratty build demo.narratty.yaml                    # container if available
narratty build demo.narratty.yaml --runtime native   # tools from your PATH
narratty build demo.narratty.yaml --runtime podman
```

## Images

| Image | Contents |
|---|---|
| `ghcr.io/ditschi/narratty:<version>` | Piper with `en_US-lessac-medium` |
| `ghcr.io/ditschi/narratty:<version>-kokoro` | The above, plus Kokoro and its model |

narratty picks the tag matching its own version (`edge` for development builds) and
the `-kokoro` variant when the spec uses Kokoro. Override the image with `--image` or
`NARRATTY_IMAGE`.

## What the container can see

| Host | Container | Access |
|---|---|---|
| the spec file | `/spec/<name>` | read-only |
| `workspace.source` | `/work` | read-write |
| the output file's directory | `/out` | read-write |
| the audio cache | `/cache` | read-write, shared with native runs |
| your downloaded voices | `/data` | read-only |

Voices are downloaded on the host before the container starts. The container runs
with no network, all capabilities dropped, `no-new-privileges`, a read-only root
filesystem and your own user id, so files it writes belong to you.
