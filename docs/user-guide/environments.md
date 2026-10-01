# Project environments

By default the demo shell runs in the narratty image. When the demo needs your
project's own toolchain, run the shell in the project's image, Compose service or dev
container instead. Only the shell moves: VHS, Chromium, the voices and ffmpeg stay in
narratty, and the project's image needs no change.

```yaml
environment:
  image: ghcr.io/acme/toolchain:2.3
  workdir: /work        # where the workspace is mounted and the shell starts
  user: host            # host (default) | image | UID[:GID]
```

The image needs Linux (amd64 or arm64) and the [`terminal.shell`](spec.md#terminal).
Without `environment`, nothing changes. Set exactly one source: `image`, `build`,
`compose`, `container` or `devcontainer`.

## Build from a Dockerfile

Instead of `image`, `build` builds the project's own Dockerfile (paths relative to the
spec). The build uses the normal build cache, so an unchanged Dockerfile is quick.

```yaml
environment:
  build:
    context: .
    dockerfile: docker/dev.Dockerfile   # default: <context>/Dockerfile
    target: dev
    args: {PY: "3.12"}
```

## Run in a Compose service

```yaml
environment:
  compose:
    file: compose.yaml    # relative to the spec
    service: dev
```

narratty starts the Compose project from the [workspace](container.md#workspace-modes)
(a snapshot by default), so the service's relative mounts such as `.:/src` point at
it. It waits until the services are up (`up --wait`), runs the demo shell in `dev`,
and removes the project with its volumes afterwards. The shell starts in the service's
`working_dir` unless `workdir` is set. Networks, mounts and privileges come from the
Compose file, including `network_mode: host`; the sandbox rules do not apply to them.

`file` also takes a list (`[compose.yaml, compose.dev.yaml]`), merged in order like
repeated `docker compose -f`.

## Use your dev container

`devcontainer` reads the project's `devcontainer.json` and runs what it describes:
its `image`, its Dockerfile (`build`) or its Compose service (`dockerComposeFile` and
`service`). VHS, the voices and ffmpeg stay in narratty; the dev container needs no
change.

```yaml
environment:
  devcontainer: .devcontainer   # the folder or the devcontainer.json, relative to the spec
```

| From `devcontainer.json` | Becomes |
|---|---|
| `image`, `build` (`dockerfile`, `context`, `args`, `target`), `dockerComposeFile` + `service` | the source |
| `workspaceFolder` | `workdir` (default `/workspaces/<folder>`) |
| `remoteUser`, `containerUser` | `user` |
| `containerEnv`, `remoteEnv` | `env` |
| `${localEnv:NAME}`, `${localWorkspaceFolder}`, `${containerWorkspaceFolder}` | their values |

Keys set in the spec win, so `user: host` keeps files the demo writes yours. JSON
with comments and trailing commas is fine.

Dev container `features`, lifecycle commands (`postCreateCommand`, ...), `runArgs`
and `mounts` need the [Dev Container CLI](https://github.com/devcontainers/cli);
narratty skips them with a note. When the container depends on them, build it once
with the CLI and record that image:

```bash
devcontainer build --workspace-folder . --image-name acme/dev:recording
```

```yaml
environment:
  image: acme/dev:recording
  workdir: /workspaces/app
```

### Example: record a build in the dev container

`examples/devcontainer` is a small project whose dev container is a Compose
service. The video runs its real build inside that container:

=== "devcontainer.json"

    ```jsonc
    --8<-- "examples/devcontainer/.devcontainer/devcontainer.json"
    ```

=== "compose.yaml"

    ```yaml
    --8<-- "examples/devcontainer/.devcontainer/compose.yaml"
    ```

=== "demo.narratty.yaml"

    ```yaml
    --8<-- "examples/devcontainer/demo.narratty.yaml"
    ```

1. Check what the demo will see: `narratty env shell demo.narratty.yaml` opens the
   shell the recording gets. Try the commands there.
2. Iterate quickly: `narratty env up demo.narratty.yaml` keeps the container running,
   so `narratty build demo.narratty.yaml --draft` skips the start-up each time.
3. Record: `narratty build demo.narratty.yaml`, then `narratty env down
   demo.narratty.yaml`.

`wait: {prompt: true}` waits until the build has finished, however long it takes (up
to `timeout_ms`). With the default `snapshot` workspace the build writes into a copy,
so the checkout stays clean. `eza` comes from the [demo toolkit](#demo-toolkit), not
from the dev container.

## Run in a running container

```yaml
environment:
  container: dev        # name or id
  user: image
workspace:
  mode: rw              # required: the demo works in the container's own files
```

narratty neither starts nor stops the container and adds no mounts; the demo shell
starts in its working directory. Use this for a dev container you already have open.

## Extra tools for the demo

When the image lacks tools the demo shows, `packages` adds them with the image's
package manager and `setup` runs further commands:

```yaml
environment:
  image: ghcr.io/acme/toolchain:2.3   # or build
  packages: [bat, jq, tree]
  package_manager: auto               # auto | apt | apk | dnf | microdnf | yum | zypper
  setup:
    - curl -fsSL https://example.com/tool.tar.gz | tar -xz -C /usr/local/bin
```

narratty builds a small image on top: root and network access only while building,
then the image's own user again. It is tagged `narratty-env:<hash>` of the base image,
the packages and the commands, so a second run builds nothing. `auto` detects the
package manager once per image; an image without one (distroless, scratch) needs
`setup` or `build`. `narratty env build SPEC` builds ahead of time, `--rebuild-env`
forces a rebuild.

Because the build runs as root with network access, the first run asks for approval,
like [sandbox permissions](container.md#you-stay-in-control). `packages` and `setup`
work with `image`, `build` and `compose`, not with a running container.

## Demo toolkit

The [toolkit](toolkit.md) (`yazi`, `bat`, `eza` and their settings) is mounted
read-only at `/.narratty/toolkit` and put first on `PATH`; nothing is installed into
the image. `toolkit: fallback` puts it last, so the image's own tools win;
`toolkit: off` leaves it out. Without the toolkit image (offline, no access to GHCR)
the demo runs without it.

## Keep it running

```bash
narratty env up demo.narratty.yaml     # start and keep the environment
narratty build demo.narratty.yaml      # uses it: no start-up, warm state
narratty env shell demo.narratty.yaml  # look around in the same container
narratty env down demo.narratty.yaml   # remove container, volumes and snapshot
```

While it runs, `build`, `render` and `env shell` reuse it instead of starting a new
one. The demo then sees what earlier runs left behind, so reset state in a hidden
scene when a video must start clean.

## How it runs

1. narratty pulls or builds the image, prepares the
   [workspace](container.md#workspace-modes) and starts the image with the workspace
   mounted at `workdir` (or starts the Compose service, or attaches to the container).
2. In a [sandboxed run](container.md), the static `narratty-agent` from the narratty
   image is mounted read-only into that container. It serves the demo shell over a
   socket in a small volume shared with the narratty container, which keeps no network
   and no access to Docker. For a running container the agent is copied in, serves one
   shell on an abstract socket and is removed afterwards. In a native run,
   `docker exec` opens the shell.
3. The recording types into that shell. The end card is drawn by narratty after the
   demo shell has exited.
4. The container is removed afterwards. `--keep-env` keeps it and prints how to enter it.
   A running container is left as it was.

## Rules and permissions

The [sandbox](container.md#sandbox-permissions) applies to the environment's container,
in native runs too: `network`, `allow_hosts`, `env`, `env_passthrough`, `extra_mounts`,
`ssh_agent` and `workspace.caches`. All capabilities are dropped and
`no-new-privileges` is set.

| `user` | Runs as | `~` in mounts and caches |
|---|---|---|
| `host` | your user id; files the demo writes belong to you | `/home/narratty` (a tmpfs, also `$HOME`) |
| `image` | the image's `USER` | the image's `$HOME` |
| `UID[:GID]` or a name | that user | the image's `$HOME` |

`env` sets variables in the environment's container (not for `container`).
`read_only: true` also mounts the image's root filesystem read-only (off by default,
since project images often write outside the workspace).

`compose` and `container` run with what the Compose file or the container already
has, so the first run asks for approval for them too.

A policy in `~/.config/narratty/config.toml` limits which kinds of environments a spec
may use:

```toml
[sandbox]
allow_environment = ["image", "build"]   # also "compose", "container", "devcontainer"; [] forbids all
allow_packages = false                   # no packages or setup commands
```

## Builds with a warm cache

Keep the checkout clean and the build fast: the default `snapshot` workspace gives
the build a writable copy, and `workspace.caches` keeps caches across runs in named
volumes.

```yaml
workspace:
  mode: snapshot                      # default; writes never reach your checkout
  caches: {bazel: ~/.cache/bazel}     # persists between runs
environment:
  image: ghcr.io/acme/toolchain:2.3
```

For a long build, `wait: {prompt: true, timeout_ms: 900000}` waits until the command
has finished and the prompt is back.

## Command line

```bash
narratty build demo.narratty.yaml                          # environment from the spec
narratty build demo.narratty.yaml --env-image acme/dev:2   # another image for this run
narratty build demo.narratty.yaml --no-env                 # demo in the narratty image
narratty build demo.narratty.yaml --keep-env               # keep the container afterwards
narratty build demo.narratty.yaml --rebuild-env            # rebuild Dockerfile and packages
narratty env build demo.narratty.yaml                      # build the image only
narratty env shell demo.narratty.yaml                      # interactive shell, same setup
narratty env up demo.narratty.yaml                         # start and keep it
narratty env down demo.narratty.yaml                       # remove it
```

`narratty env shell` starts the environment like a build would, with the same bridge,
and opens an interactive `terminal.shell` in it, to check what the demo will see.

## Limits

- Initialisation from the image's `ENTRYPOINT` (for example `conda activate`) does not
  run; the container starts `terminal.shell` directly. Put that setup into a hidden
  scene.
- An image for another architecture runs under emulation, which is slow.
- Windows containers are not supported.
