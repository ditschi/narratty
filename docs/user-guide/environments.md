# Project environments

By default the demo shell runs in the narratty image. When the demo needs your
project's own toolchain, run the shell in the project's image instead. Only the shell
moves: VHS, Chromium, the voices and ffmpeg stay in narratty.

```yaml
environment:
  image: ghcr.io/acme/toolchain:2.3
  workdir: /work        # where the workspace is mounted and the shell starts
  user: host            # host (default) | image | UID[:GID]
```

The image needs Linux (amd64 or arm64) and the [`terminal.shell`](spec.md#terminal).
Without `environment`, nothing changes.

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
like [sandbox permissions](container.md#you-stay-in-control).

## How it runs

1. narratty pulls or builds the image, prepares the
   [workspace](container.md#workspace-modes) and starts the image with the workspace
   mounted at `workdir`.
2. In a [sandboxed run](container.md), the static `narratty-agent` from the narratty
   image is mounted read-only into that container. It serves the demo shell over a
   socket in a small volume shared with the narratty container, which keeps no network
   and no access to Docker. In a native run, `docker exec` opens the shell.
3. The recording types into that shell. The end card is drawn by narratty after the
   demo shell has exited.
4. The container is removed afterwards. `--keep-env` keeps it and prints how to enter it.

## Rules and permissions

The [sandbox](container.md#sandbox-permissions) applies to the environment's container,
in native runs too: `network`, `allow_hosts`, `env`, `env_passthrough`, `extra_mounts`,
`ssh_agent` and `workspace.caches`. All capabilities are dropped and
`no-new-privileges` is set.

| `user` | Runs as | `~` in mounts and caches |
|---|---|---|
| `host` | your user id; files the demo writes belong to you | `/home/narratty` (a tmpfs, also `$HOME`) |
| `image` | the image's `USER` | the image's `$HOME` |
| `UID[:GID]` | that id | the image's `$HOME` |

`read_only: true` also mounts the image's root filesystem read-only (off by default,
since project images often write outside the workspace).

A policy in `~/.config/narratty/config.toml` limits which kinds of environments a spec
may use:

```toml
[sandbox]
allow_environment = ["image", "build"]   # [] forbids environments
allow_packages = false                   # no packages or setup commands
```

## Command line

```bash
narratty build demo.narratty.yaml                          # environment from the spec
narratty build demo.narratty.yaml --env-image acme/dev:2   # another image for this run
narratty build demo.narratty.yaml --no-env                 # demo in the narratty image
narratty build demo.narratty.yaml --keep-env               # keep the container afterwards
narratty build demo.narratty.yaml --rebuild-env            # rebuild Dockerfile and packages
narratty env build demo.narratty.yaml                      # build the image only
narratty env shell demo.narratty.yaml                      # interactive shell, same setup
```

`narratty env shell` starts the environment like a build would, with the same bridge,
and opens an interactive `terminal.shell` in it, to check what the demo will see.

## Limits

- Initialisation from the image's `ENTRYPOINT` (for example `conda activate`) does not
  run; the container starts `terminal.shell` directly. Put that setup into a hidden
  scene.
- An image for another architecture runs under emulation, which is slow.
- Windows containers are not supported.
