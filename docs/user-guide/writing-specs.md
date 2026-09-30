# Writing specs

A good spec reads like a script: narration and the commands, nothing else. The
defaults cover the common case, so write only what differs from them.

## Leave out the defaults

Every key has a default (see the [spec reference](spec.md)). This is a complete spec:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ditschi/narratty/main/schema/v1.json
scenes:
  - id: intro
    narration: This is a quick tour of the repository layout.
    actions:
      - run: ls -la
```

Repeating defaults such as `tts: {provider: kokoro, voice: af_heart}` or the terminal
size only makes the spec longer and hides the settings that matter.

## Scenes wait for their narration

A scene lasts until its actions are done and its narration has finished, plus
`timing.narration_buffer_ms`. The pause that fills the gap goes after the last
action. So:

- A scene that only talks needs no `actions`.
- `hold: auto` at the end of a scene does nothing extra. Use it only in the middle of a
  scene, when the actions after it should wait for the narration.

```yaml
# not needed
- id: intro
  narration: This demo looks like an editor.
  actions:
    - hold: auto

# enough
- id: intro
  narration: This demo looks like an editor.
```

```yaml
# hold: auto in the middle: show the result while talking, then clear the screen
- id: result
  narration: The build is green, all tests passed.
  actions:
    - run: make test
    - wait: passed
    - hold: auto
    - ctrl_sequence: C-l
```

## `run` for commands, `type_command` for typing

`run` types a command, presses Enter and pauses for `timing.run_hold_ms` (500 ms), so
the viewer sees the output before the next command is typed.

```yaml
# long form
- type_command: git status
- enter
- hold: 500

# same thing
- run: git status
```

Use `type_command` for input that is not a finished command: text in an editor, a
prompt that is answered later, or a command that is edited before Enter.

Change the pause for every `run` in the spec with `timing.run_hold_ms`. For a single
longer pause, add a `hold` after that `run`.

## Wait for output instead of guessing

A command that takes a moment should be followed by `wait`, not by a long `hold`. The
video then continues as soon as the output is there:

```yaml
- run: docker compose up -d
- wait: Started
```

`wait: "pattern"` uses the default timeout of 15 seconds. Give the mapping form only
for a different timeout:

```yaml
- wait: {screen: "Successfully built", timeout_ms: 300000}
```

Slow setup (installs, builds, downloads) belongs in a `hidden: true` scene, which is
run but not recorded.

## Only divergent values per scene

Set a value once at the top and override it only where a scene differs:

```yaml
terminal:
  typing_speed_ms: 30          # the whole video types a bit faster

scenes:
  - id: long-command
    typing_speed_ms: 10        # this one command would take too long otherwise
    actions:
      - run: docker run --rm -v "$PWD:/work" -w /work ghcr.io/acme/tool:latest check
```

## YAML pitfalls

- List items start with `- `. `* item` is Markdown, not YAML (`*` starts an alias),
  and fails to parse.
- Quote text that contains `: `, `#` or starts with a special character
  (`*`, `&`, `!`, `%`, `@`, `` ` ``, `{`, `[`).
- `>-` folds a long command over several lines; a line break becomes a space.
- Comments (`#`) inside a `>` or `|` block are part of the text.

`narratty validate` reports every problem with its line and column. With the schema
line at the top, editors show the same problems while you type.

## Specs written by an AI agent

Point the agent at this page and let it run `narratty validate` after each change.
Ask it to keep the spec to the non-default values.
