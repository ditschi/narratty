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
| `docker` | `false` | Give the demo your Docker or Podman engine; [full host access](container.md#docker-in-the-demo) |

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

A scene has at most one `hold: auto`, and only when it has narration.
