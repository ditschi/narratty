# Demo toolkit

The toolkit is a set of statically linked command-line tools that look good in
recordings, plus settings tuned for video. It runs in any Linux image (Debian, Ubuntu,
Alpine, UBI, even busybox), as any user, without a package manager.

| Tool | Use in demos |
|---|---|
| `bat` | Show files with syntax highlighting |
| `eza` | `ls` and `eza --tree` with colours and icons |
| `fd`, `rg` | Find files and text |
| `jq` | Pretty-print JSON |
| `yazi` | File explorer with a preview |
| `tmux` | Split the terminal into panes |
| `zsh` | Alternative shell (`terminal.shell: zsh`) |

It also brings the Symbols Nerd Font (icons in `yazi` and `eza --icons`), a
`tmux.conf` with a quiet status line and titled panes, and configs for `yazi` and
`bat`. Licenses are in `/usr/local/share/narratty/licenses`.

## In the narratty image

The narratty image contains the toolkit, with its settings active. Specs that run in
the container can use all tools directly.

## In your own image

The toolkit is published as `ghcr.io/ditschi/narratty-toolkit`, an image that holds
only these files. Add it to a Dockerfile with one line:

```dockerfile
COPY --from=ghcr.io/ditschi/narratty-toolkit:latest / /usr/local/
ENV YAZI_CONFIG_HOME=/usr/local/share/narratty/yazi \
    BAT_CONFIG_PATH=/usr/local/share/narratty/bat/config
```

- The target must be `/usr/local`: `zsh` and `tmux` look for their files there.
- `COPY` needs no `USER root`, and nothing is installed at run time.
- Instead of the `ENV` lines, a shell can load the settings with
  `. /usr/local/share/narratty/env.sh`. `tmux` reads its settings from
  `/usr/local/etc/tmux.conf` on its own; a `~/.tmux.conf` still wins.
- Images exist for `linux/amd64` and `linux/arm64`. Tags follow narratty's versions
  (`<version>`, `<major.minor>`, `latest`, `edge`); pin a version for reproducible
  builds.

## In a dev container

The toolkit goes into the image the dev container is built from. Pick the case that
matches your setup.

**`devcontainer.json` with a Dockerfile.** Add the lines to that Dockerfile. In a
multi-stage Dockerfile, add them to the stage the dev container uses (`build.target`):

```dockerfile
# .devcontainer/Dockerfile
FROM mcr.microsoft.com/devcontainers/python:3.12
# ... your setup ...
COPY --from=ghcr.io/ditschi/narratty-toolkit:latest / /usr/local/
ENV YAZI_CONFIG_HOME=/usr/local/share/narratty/yazi \
    BAT_CONFIG_PATH=/usr/local/share/narratty/bat/config
```

**`devcontainer.json` with only `image`.** Replace `image` with a build of a
two-line Dockerfile:

```jsonc
// .devcontainer/devcontainer.json
{
  "build": { "dockerfile": "Dockerfile" }   // was: "image": "ghcr.io/acme/dev:2"
}
```

```dockerfile
# .devcontainer/Dockerfile
FROM ghcr.io/acme/dev:2
COPY --from=ghcr.io/ditschi/narratty-toolkit:latest / /usr/local/
ENV YAZI_CONFIG_HOME=/usr/local/share/narratty/yazi \
    BAT_CONFIG_PATH=/usr/local/share/narratty/bat/config
```

**Docker Compose, without touching the project.** An override file adds the toolkit
on top of the service's image with an inline Dockerfile (Compose 2.17 or later):

```yaml
# compose.narratty.yaml
services:
  dev:
    image: acme-dev:narratty          # own tag, the original image stays as it is
    build: !override                  # replaces the service's own build settings
      dockerfile_inline: |
        FROM ghcr.io/acme/dev:2
        COPY --from=ghcr.io/ditschi/narratty-toolkit:latest / /usr/local/
        ENV YAZI_CONFIG_HOME=/usr/local/share/narratty/yazi \
            BAT_CONFIG_PATH=/usr/local/share/narratty/bat/config
```

```bash
docker compose -f compose.yaml -f compose.narratty.yaml up -d --build
docker compose -f compose.yaml -f compose.narratty.yaml exec dev bash
```

If the service is built from its own Dockerfile (`build:` in `compose.yaml`), build
it first without the override and use its image name after `FROM`:

```bash
docker compose build dev
docker compose config --images      # the image name to put after FROM
```

The dev container keeps its user; nothing runs as root at run time.

## Onboarding videos

A video that clones a repository, starts its dev container and works inside it needs
Docker during the recording. Either give the sandboxed demo your engine with
`sandbox.docker: true` ([full host access](container.md#docker-in-the-demo), you
approve it once), or run with `--runtime native`:

```yaml
sandbox:
  docker: true
  network: allowlist                   # for git clone
  allow_hosts: [github.com:443]
scenes:
  - id: clone
    narration: Clone the repository.
    actions:
      - type_command: git clone https://github.com/acme/app && cd app
      - enter
      - wait: {screen: "done\\.", timeout_ms: 120000}
  - id: toolkit                  # add the toolkit, unrecorded
    hidden: true
    actions:
      - type_command: >-
          echo 'COPY --from=ghcr.io/ditschi/narratty-toolkit:latest / /usr/local/'
          >> .devcontainer/Dockerfile
      - enter
  - id: build
    narration: Build and start the dev container. This is sped up.
    actions:
      - type_command: docker compose up -d --build && echo rea""dy
      - enter
  - id: build-runs               # the build output, ten times faster
    timelapse: 10
    actions:
      - wait: {screen: "\\nready", timeout_ms: 900000}
  - id: enter
    narration: Open a shell in the dev container.
    actions:
      - type_command: docker compose exec dev bash
      - enter
      - hold: auto
  - id: settings
    hidden: true
    actions:
      - type_command: . /usr/local/share/narratty/env.sh
      - enter
  - id: explore
    narration: This is the project inside the container.
    actions:
      - type_command: eza --tree --level 2
      - enter
      - hold: auto
```

Things to watch:

- A [timelapse](spec.md#timelapse) scene shows the build sped up. To leave it out
  instead, make the scene `hidden: true`: hidden scenes take no time in the video,
  and the screen is cleared after them.
- `echo rea""dy` prints `ready`, but the typed command does not match the `wait`.
- Instead of editing the Dockerfile, the hidden scene can write the
  [Compose override](#in-a-dev-container) and start with both files.
- The appended `COPY` line lands in the last stage of the Dockerfile. If the dev
  container builds an earlier stage (`target:`), add it there.
- Viewers who follow the video do not have that line. Use the toolkit to show the
  project, not for steps they are meant to repeat.
- The dev container keeps running after the render. End with a hidden scene that
  leaves it (`exit`) and runs `docker compose down`.

## Example: an editor-like layout

`examples/editor-layout` records a layout like an editor: `yazi` as explorer and
preview on top, a shell below. A hidden first scene builds the layout:

```yaml
- id: layout
  hidden: true
  actions:
    - type_command: >-
        tmux new-session -s ide yazi \;
        split-window -v -l 30% "PS1='$ ' bash --norc" \;
        select-pane -t 1 -T Explorer \; select-pane -t 2 -T Terminal
    - enter
    - wait: {screen: "Terminal"}
```

The scenes after it press `Ctrl+b` and an arrow key to move between the panes
(`ctrl_sequence: C-b`, `key: Up`) and use the arrow keys in the explorer. A hidden last
scene runs `tmux kill-server`, so the end card gets the whole terminal.

<video controls width="100%" src="../../assets/editor-layout.mp4"></video>

```bash
narratty build examples/editor-layout/editor.narratty.yaml
```
