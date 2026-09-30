# Sandboxed runs

With Docker or Podman installed, `build`, `render`, `tts`, `plan` and `tape` run
inside the narratty image by default (`--runtime auto`). The image contains VHS,
ttyd, Chromium, ffmpeg, fonts, Kokoro, Piper, `git`, `tree` and the [demo toolkit](toolkit.md)
(`bat`, `eza`, `fd`, `ripgrep`, `jq`, `yazi`, `tmux`, `zsh`). You only need narratty
itself and a container runtime on the host.

To run the demo shell in your project's own image instead, see
[Project environments](environments.md).

```bash
narratty build demo.narratty.yaml                    # container if available
narratty build demo.narratty.yaml --runtime native   # tools from your PATH
narratty build demo.narratty.yaml --runtime podman
```

## Images

| Image | Contents |
|---|---|
| `ghcr.io/ditschi/narratty:<version>` | Kokoro with `af_heart`, Piper with `en_US-lessac-medium` |
| `ghcr.io/ditschi/narratty-toolkit:<version>` | Only the [demo toolkit](toolkit.md), to copy into other images |

narratty picks the tag matching its own version (`edge` for development builds).
Override the image with `--image` or `NARRATTY_IMAGE`. Up to 0.1, Kokoro needed a
separate `-kokoro` image; from 0.2 on, the one image has both engines.

## What the container can see

| Host | Container | Access |
|---|---|---|
| the spec file | `/spec/<name>` | read-only |
| the prepared workspace (see below) | `/work` | read-write, or read-only with `ro` |
| the output file's directory | `/out` | read-write |
| the audio cache | `/cache` | read-write, shared with native runs |
| your downloaded voices | `/data` | read-only |

Voices are downloaded on the host before the container starts. The container runs
with no network, all capabilities dropped, `no-new-privileges`, a read-only root
filesystem and your own user id, so files it writes belong to you.

## Workspace modes

`workspace.mode` decides what directory the demo runs in. `--workspace-mode`
overrides it for one run.

| Mode | Runs in | Use it when |
|---|---|---|
| `snapshot` (default) | a throwaway copy: for git repositories a local clone of `HEAD` plus your uncommitted and untracked files (not ignored ones) | the demo builds or writes files; your checkout stays untouched |
| `rw` | the real directory | build results should stay in the repository; refused on a tree with uncommitted changes unless `--allow-dirty`, and afterwards narratty lists the files the demo changed |
| `ro` | the real directory, read-only | the demo only reads; enforced in the container only |

`--keep-workspace` keeps the snapshot (under the cache directory) for inspection.
`workspace.include_uncommitted: false` snapshots exactly `HEAD`.

Files the demo produces can be copied out with `workspace.artifacts`, a list of globs
relative to the workspace. They land next to the video in `<name>.artifacts/`.

`workspace.caches` maps a name to a directory inside the container
(e.g. `bazel: ~/.cache/bazel`). Each is a directory under the cache directory on the
host that persists across runs, so builds in the demo stay fast. In native mode your
real cache directories are used.

## Sandbox permissions

A spec declares what else the demo needs:

```yaml
sandbox:
  network: allowlist               # none (default) | allowlist | full
  allow_hosts:
    - license.example.com:27000
    - cache.example.com:443
  env_passthrough: [LM_LICENSE_FILE]   # copied from your shell, never stored in the spec
  env: {TZ: UTC}
  extra_mounts:
    - {host: ~/.netrc, container: ~/.netrc, mode: ro}
  ssh_agent: false
```

- **`network: allowlist`** puts the container on an internal network with no route
  out. For each allowed host a small forwarder (in the same image) joins that network
  under the host's name and passes its ports through to the real host, which narratty
  resolves on your machine. TCP is forwarded as is, so licence servers, TLS (with SNI
  and certificates intact) and other protocols work without proxy settings. Nothing
  else is reachable.
- **`network: full`** uses the container runtime's normal network.
- `--network none|allowlist|full` and `--allow-host HOST:PORT` (repeatable) override
  the spec for one run.

### You stay in control

The first run of a spec that asks for more than the defaults lists what it wants and
asks for approval. The answer is remembered for that spec file and that exact
`sandbox` block, so a changed spec asks again. Pass `--yes` (or set `NARRATTY_YES=1`)
in CI.

A policy in `~/.config/narratty/config.toml` caps what any spec may get:

```toml
[sandbox]
max_network = "allowlist"          # none | allowlist | full
allow_env = ["LM_LICENSE_FILE"]    # env_passthrough names a spec may use
allow_mounts = true
allow_ssh_agent = false
```

A spec that needs more than the policy allows fails with a message naming what is
over the limit.

In native mode none of this can be enforced: the demo runs with your own network and
environment, and narratty says so. `sandbox.env` is still applied.
