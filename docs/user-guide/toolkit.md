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

## Onboarding videos

A video that clones a repository, starts its dev container and works inside it needs
Docker during the recording. Run it with `--runtime native`, so the demo uses Docker
on your machine:

```yaml
scenes:
  - id: clone
    narration: Clone the repository.
    actions:
      - type_command: git clone https://github.com/acme/app && cd app
      - enter
      - wait: {screen: "done\\.", timeout_ms: 120000}
  - id: build                    # add the toolkit and build, both unrecorded
    hidden: true
    actions:
      - type_command: >-
          echo 'COPY --from=ghcr.io/ditschi/narratty-toolkit:latest / /usr/local/'
          >> .devcontainer/Dockerfile &&
          docker compose up -d --build >/tmp/build.log 2>&1 && echo ready
      - enter
      - wait: {screen: "ready", timeout_ms: 900000}
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

- Hidden scenes take no time in the video, so long downloads and builds disappear.
  After a hidden scene the screen is cleared.
- The appended `COPY` line lands in the last stage of the Dockerfile. If the dev
  container builds an earlier stage (`target:`), add it there.
- Viewers who follow the video do not have that line. Use the toolkit to show the
  project, not for steps they are meant to repeat.

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
