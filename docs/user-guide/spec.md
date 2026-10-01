# Spec reference

A narratty video is described by a `.narratty.yaml` file. `narratty init` writes a
commented starter, `narratty validate` checks one, and `narratty schema` prints the JSON
Schema.

## Editor support

The first line `narratty init` writes tells your editor where the schema is:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ditschi/narratty/v0.2.0/schema/v1.json
```

Editors that use [yaml-language-server](https://github.com/redhat-developer/yaml-language-server)
read that comment and then offer completion, hover docs and inline errors for the
spec: VS Code with the Red Hat YAML extension, Neovim or Helix with `yaml-language-server`,
and JetBrains IDEs. The schema is committed to the repository as `schema/v1.json`,
so each release tag serves the schema of that release. `init` points the line at the
tag of the narratty version you have installed; development builds point at `main`.

Offline, or to pin a local copy, write the schema to a file and reference it relatively:

```bash
narratty schema > .narratty.schema.json
```

```yaml
# yaml-language-server: $schema=./.narratty.schema.json
```

Unknown keys are errors, and `validate` reports every problem with its line and column,
plus a "did you mean" for typos:

```text
$ narratty validate demo.narratty.yaml
demo.narratty.yaml:4:9: scenes[0].actions[0]: unknown action 'type_comand' (did you mean 'type_command'?)
```

## Top level

| Key | Default | Meaning |
|---|---|---|
| `version` | `1` | Spec format version |
| `meta.title` | `Untitled` | Title of the video |
| `tts` | | Voice settings, see below |
| `timing` | | Sync settings, see below |
| `terminal` | | Look of the recorded terminal |
| `requires.tools` | `[]` | Extra commands the demo needs (checked by `doctor`) |
| `workspace` | | What directory the demo runs in |
| `sandbox` | | Permissions of the container |
| `end_card` | on | Closing card, see below |
| `subtitles` | `none` | `none`, `files`, `track` or `burn`; see [Subtitles](building.md#subtitles) |
| `overlay_styles` | `{}` | Named overlay styles; see [Overlays](#overlays) |
| `scenes` | required | At least one scene |

## `tts`

| Key | Default | Meaning |
|---|---|---|
| `provider` | `kokoro` | `kokoro` or `piper` |
| `voice` | `af_heart` (`en_US-lessac-medium` with `piper`) | Voice id; see [Voices](voices.md) |
| `piper.length_scale` | `1.0` | Larger is slower speech |
| `piper.sentence_silence` | `0.2` | Seconds of silence between sentences |
| `kokoro.speed` | `1.0` | Speech speed |
| `kokoro.lang` | voice's language | Language code, e.g. `en-gb` |
| `lexicon` | `{}` | How to say terms, e.g. `{k8s: kubernetes}`; see [Pronunciation](voices.md#pronunciation) |

## `timing`

| Key | Default | Meaning |
|---|---|---|
| `narration_buffer_ms` | `500` | Pause after each narration before the next scene |
| `lead_in_ms` | `300` | Silence before the first scene |
| `tail_ms` | `1000` | Time the last frame stays on screen |

## `terminal`

| Key | Default | Meaning |
|---|---|---|
| `width`, `height` | `1200`, `700` | Video size in pixels |
| `theme` | `Dracula` | Any VHS theme |
| `font_size` | `22` | Font size |
| `typing_speed_ms` | `40` | Time per typed key |
| `shell` | `bash` | `bash`, `zsh`, `fish` or `sh` |
| `prompt` | `"$ "` | Prompt shown in the recording |

## `workspace`

| Key | Default | Meaning |
|---|---|---|
| `source` | `.` | Directory the demo runs in, relative to the spec |
| `mode` | `snapshot` | `snapshot` (throwaway copy), `rw` (the real directory) or `ro` (read-only) |
| `include_uncommitted` | `true` | Copy uncommitted files into the snapshot |
| `caches` | `{}` | Named cache volumes, `name: /path/in/container` |
| `artifacts` | `[]` | Paths copied out of the workspace after the run |

## `sandbox`

Only used when the demo runs in a container. Anything beyond the defaults is shown to
you for approval before the first run.

| Key | Default | Meaning |
|---|---|---|
| `network` | `none` | `none`, `allowlist` or `full` |
| `allow_hosts` | `[]` | `host:port` entries, required with `allowlist` |
| `env_passthrough` | `[]` | Host environment variables passed in |
| `env` | `{}` | Fixed environment variables |
| `extra_mounts` | `[]` | `{host, container, mode: ro\|rw}` |
| `ssh_agent` | `false` | Forward the host SSH agent |

## `end_card`

The video ends with a short card that says "Created with narratty", with a link to
this documentation and a QR code of the link. The QR code sits beside the text, or
above it on a narrow terminal; it is left out when the terminal is too small for it.
The card is drawn in black and white so it scans on any theme.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | unset | `true` or `false`; unset follows your config (on by default) |
| `duration_ms` | `4000` | How long the card stays on screen (at least 1000) |
| `qr` | `true` | Show the QR code |

`end_card: false` is short for `end_card: {enabled: false}`. To turn the card off for
every video, put this in `~/.config/narratty/config.toml`:

```toml
[end_card]
enabled = false
```

`--end-card` / `--no-end-card` on the command line win over the spec, and the spec
wins over the config.

## Scenes

| Key | Default | Meaning |
|---|---|---|
| `id` | required | Lowercase letters, digits, `-` and `_`; unique |
| `narration` | none | Text spoken while the scene plays |
| `actions` | `[]` | What happens in the terminal |
| `hidden` | `false` | Run without recording (setup); cannot have narration |
| `typing_speed_ms` | terminal's | Per-scene typing speed |
| `narration_start` | `with_actions` | Or `after_actions` |

A scene lasts as long as its actions or its narration plus `narration_buffer_ms`,
whichever is longer.

### Actions

| Action | Example | Does |
|---|---|---|
| `type_command` | `- type_command: "ls -la"` | Types the text |
| `enter` | `- enter` | Presses Enter |
| `ctrl_sequence` | `- ctrl_sequence: C-c` | Presses Ctrl plus a key |
| `key` | `- key: Up` or `- key: Down 3` | Presses a named VHS key, optionally repeated |
| `hold` | `- hold: 1500` or `- hold: auto` | Waits; `auto` waits until the narration is done |
| `wait` | `- wait: {screen: "Done", timeout_ms: 15000}` | Waits until the screen matches a regex |
| `overlay` | `- overlay: "Open src/main.py"` | Shows text over the video; see [Overlays](#overlays) |
| `browser` | `- browser: docs/site/index.html` | Shows a web page over the terminal; see [Browser views](#browser-views) |

A scene has at most one `hold: auto`, and only when it has narration.

### Overlays

An overlay shows text over the video, in a rounded, semi-transparent box: a chapter
title, the file the narration talks about. It stays readable while the terminal
scrolls.

![Overlays: a chapter, a file name, a custom style and text without a box](../assets/overlays.png)

```yaml
overlay_styles:
  file: {position: top, size: small, color: "#f1fa8c"}

scenes:
  - id: setup
    narration: Let's set up the project.
    actions:
      - overlay: {text: "1 · Setup", style: chapter}
      - type_command: make setup
      - enter
      - overlay: Run the tests next
      - overlay: {text: src/greet/__main__.py, style: file, duration_ms: 3000}
```

The overlay appears where its action stands in the scene. It stays until the first
of: `duration_ms` has passed, another overlay takes its position, or the scene ends.
With `keep: true` it stays past the scene until another overlay takes its position
(the `chapter` style keeps). The box is sized around the text; `\n` starts a new
line. The top right is usually free of terminal text; the bottom is shared with
[burned-in subtitles](building.md#subtitles).

In the mp4, an overlay's time comes from the planned timeline, so one placed right
after a `wait` for a slow command can show up early. Put it before the `wait`, or at
the start of the next scene.

`overlay: "text"` uses the `default` style. A mapping takes `text`, an optional
`style` and any style key to change just this overlay:

| Style key | `default` | Meaning |
|---|---|---|
| `position` | `bottom-right` | `top-left`, `top`, `top-right`, `left`, `center`, `right`, `bottom-left`, `bottom`, `bottom-right` |
| `size` | `medium` | `small`, `medium`, `large`, or a factor of `terminal.font_size` (`1.3` = medium) |
| `color` | `#ffffff` | Text colour, `#rrggbb` |
| `background` | `#000000b3` | Box colour, `#rrggbbaa` (the last two digits are the opacity) |
| `box` | `true` | `false` shows the text alone, with a dark outline |
| `bold` | `false` | Bold text |
| `duration_ms` | unset | Hide after this long |
| `keep` | `false` | Stay past the end of the scene |

Built-in styles: `default` (above) and `chapter` (`top-right`, `large`, bold, `keep`).
`overlay_styles` changes them or adds your own; each style starts from `default`, so
it only lists what differs. Overlays fade in and out. They need the mp4 to be
re-encoded, which `build` does when a spec has any; in the [cast page](building.md#asciicast-with-narration)
they are drawn over the player and follow its clock.

### Browser views

A browser view shows a web page or a local HTML file as a browser renders it, for
example the rendered documentation next to its Markdown source. Chromium (which VHS
records with) captures the page at the video's width; the view covers the terminal
under an address bar until its scene ends.

```yaml
sandbox:
  network: full       # only for web pages; local files need no network
scenes:
  - id: page
    narration: This is the page you should see.
    actions:
      - browser: {url: "https://github.com/ditschi/narratty", scroll: 1400}
  - id: docs
    narration: The built documentation looks like this.
    actions:
      - type_command: mkdocs build
      - enter
      - wait: {screen: "Documentation built"}
      - browser: {url: site/index.html, scroll: auto}
```

| Key | Default | Meaning |
|---|---|---|
| `url` | required | An `http(s)` URL, or an HTML file in the workspace |
| `scroll` | `none` | `auto` scrolls to the end of the page (at most 4 screens), a number scrolls that many pixels |
| `duration_ms` | unset | Hide after this long |
| `load_ms` | `5000` | How long the page may load before it is captured |

`browser: URL` is short for `browser: {url: URL}`. The page is captured once, after
it has loaded; scrolling pauses a moment at the top and at the bottom and takes the
rest of the time the view is shown. A later view in the same scene replaces an
earlier one, and overlays are drawn on top. Web pages need network access: in the
container that is `sandbox: {network: full}`. Prefer local files for pages behind a
login; narratty never signs in. The whole example is in
[`examples/browser`](https://github.com/ditschi/narratty/tree/main/examples/browser).
