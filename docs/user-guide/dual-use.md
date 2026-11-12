# Docs for reading and listening

A narratty doc serves two audiences from one file: someone **reading** it in a browser
and someone **watching** the video. The goal is one source of truth: plain Markdown that
reads well, with as few `<!-- narratty: … -->` comments as possible. Every comment is a
"parallel world" that readers don't see and that can drift from the text around it.

This page collects the rules that keep the two in step. They come from authors who
wrote tutorials, architecture overviews and runbooks with narratty and retrofitted
existing guides to it.

## The scene model in one paragraph

The doc is read top to bottom. Paragraphs collect until a code block runs, and then
they become the narration of the scene that runs it. **Narration and typing start
together**: by default the voice talks *while* the command is typed and runs. A
paragraph after a block is spoken in the next scene, while the output is still on
screen. Everything else follows from this. See [How a doc becomes scenes](markdown.md#how-a-doc-becomes-scenes).

## Rules

### Write for the ear first, then check the page

1. **Keep the paragraph before a command short.** One or two sentences that say *what*
   the command does. It is spoken while the command is typed, so a long intro talks
   over output that is already done.
2. **Explain output after the block.** A paragraph after a block is spoken while the
   output is on screen. That is the natural "run, then explain".
3. **End a lead-in with a colon.** "Check that it works:" reads well on the page and
   tells the listener a command follows.
4. **Avoid spatial and UI words.** "Above", "below", "the command below", "click here"
   and "press Ctrl+C" make no sense when spoken. Write "next", "this command" or
   "the output shows" instead.
5. **Say what kind of callout it is.** Admonition titles are not spoken. Start a
   warning with "Be careful:" or "Note that" in the text itself, so both audiences hear
   it.
6. **Don't use footnotes, task lists (`- [ ]`) or inline images in narrated text.**
   They are read literally or dropped. Use a plain sentence or a plain list.
7. **Spell out what TTS gets wrong in the lexicon, not in the text.** Run
   `narratty lexicon check` and add terms such as `JWT` or `config.yaml` to
   `tts.lexicon` in the `spec` comment. The text stays correct for readers.

### Make every block do what it shows

8. **Label every shell fence.** Use `console` with `$` prompts and the real output.
   Unlabelled fences and other languages without a `title` are **left out silently**.
   Run `narratty plan --sources` and look for "left out".
9. **Write commands that end on their own.** `tail -f`, a foreground server or a
   prompt that waits for input never return, and the build times out. Pipe them through
   something that stops (`| sed '/ready/q'`, `| head -n 20`), or start servers in the
   background with their output redirected (`app > app.log 2>&1 &`).
10. **Shorten long output in the command, not only in the doc.** `...` in a console
    block makes `narratty check` accept the rest, but the video still shows the full
    output. `| head -n 5` keeps the screen and the page consistent.
11. **Make expected failures fail for real** and mark them `expect-failure`. `check`
    verifies both the exit code and the output, so a "failing" example that actually
    succeeds is caught.
12. **Print a trailing newline.** Output without one (`curl -s` on a JSON API) leaves
    the prompt on the same line and can make the build time out. Use `curl -s -w '\n'`.
13. **Write placeholders as environment variables** (`$TOKEN`, not `<token>`) and pass
    secrets with `sandbox.env_passthrough`. Never put a secret in a `hidden` comment:
    its text ends up in work and cache files.

### Keep the parallel world small

14. **Prefer a Markdown construct over a comment.** A table with a `table` comment, a
    diagram with `focus` comments and a heading for each step all read well on the
    page. A `say` that replaces a paragraph does not.
15. **Put video-only setup in one place.** A single `hidden` block at the top of the
    first section (PATH, git identity, demo data) is easier to keep right than many
    small ones. Better still, describe the toolchain with `environment` in the `spec`
    comment.
16. **Give a block an id before you override it.** `{#install}` survives edits around
    it, scene numbers don't. Keep timing overrides in the `spec` comment at the top so
    a single-file doc stays single-file.
17. **Use `skip` + `say` only for steps the demo environment already did** (cloning,
    installing system packages), and keep the `say` to one sentence.
18. **Use `no-run` for commands viewers should see but the video must not run**
    (`sudo`, editors, `open`). Today the line ends with a visible `^C`, so say in the
    text that the step is shown, not run.

### Check before you build

19. **Run `narratty check` after every edit.** It takes seconds, runs the commands
    as the video would and finds doc bugs, not just video bugs. "0 commands ran" means
    nothing is wired up.
20. **Run `narratty plan --sources`** to see what each Markdown element became, and
    what was left out.
21. **Look at the video at section changes.** Stale output and overlay collisions only
    show there. Extract frames with `ffmpeg -ss <t> -i out.mp4 -frames:v 1 f.png`.
22. **Build on an idle machine.** Under heavy load VHS drops frames, the video comes out
    shorter than planned and the drift check fails.

## What each element becomes

| Element | On the page | In the video | Recommendation |
|---|---|---|---|
| Heading | Structure | Chapter overlay (`heading_overlays`) | One heading per step; it also scopes `sections` |
| Paragraph | Text | Narration of the next block's scene | Short before a block, explanations after it |
| `console` block | Command and output | Typed, run, output compared by `check` | The default for shell examples |
| `bash` block | Script | Each command runs; output not compared | Use for scripts readers copy as a whole |
| Code with `title` | File listing | Written hidden, shown with `cat` and a file overlay | Config files the demo needs |
| Code without `title` | Listing | Left out | Add a `title` if the video should show it |
| Table | Table | Left out; slide with a `table` or `slide` comment | Decisions and comparisons: `table {say: "If {A}, {B}."}` |
| `mermaid` | Diagram | Slide; `focus` comments walk the nodes | Flowcharts, one short paragraph per node |
| Image on its own line | Image | Slide while the text around it is spoken | Alt text is not used; describe it in the text |
| Admonition | Callout with title | Spoken without the title | Say the type in the first words |
| Collapsed block, `<details>` | Hidden until opened | Left out | Reader-only background, FAQ |
| Content tabs | Tabs | First tab, or the one the entry names | Keep tabs equivalent |
| Footnote, task list | Rendered | Read literally | Avoid in narrated sections |
| Inline code, links | Formatted | Plain text, lexicon applies | Fine; avoid bare URLs |

## Choosing who goes first: voice or command

| You want | Write | Today |
|---|---|---|
| Talk while it runs | Paragraph, then block | Default |
| Run, then explain the output | Block, then paragraph | Default for the paragraph after a block |
| Explain first, then run | Paragraph, then block, with an override `before: [{hold: auto}]` on the block id | Needs an `overrides` entry |
| Let the output sink in | `<!-- narratty: pause 2s -->` after the block | Comment |
| Speak after the commands finished | `narration_start: after_actions` in the block's override | Needs an `overrides` entry |

Narration is synchronized to the recording linearly, so on a slow command these
intentions can drift by a second or two. Keep commands quick in narrated scenes.

## Retrofitting an existing guide

1. Build it as it is and run `narratty check` and `plan --sources`. Typical result:
   most blocks are left out because the fences have no language.
2. Label shell fences `console`; keep the `$` prompts and replace volatile output
   (versions, timings) with `...`.
3. Split blocks so that commands with different needs (run, `no-run`, hidden) are in
   separate blocks.
4. Turn commands that only appear inline in a step ("run `make lint`") into blocks. This
   helps readers too.
5. Mark host-only steps `no-run` and steps the demo has already done `skip` + `say`.
6. Pick the sections for the video with `sections`; keep FAQ and troubleshooting out
   and check that the intro is still spoken.
7. Add a `table` comment to tables the video needs and `focus` comments to diagrams.
8. Remove "above"/"below" wording, say callout types in the text, and drop footnotes
   from narrated sections.

Expect to change about a sixth of the reader-visible text, and most of those changes
improve the written guide as well.

## Agents

The repository ships an agent skill that applies these rules when writing or
retrofitting a doc: `skills/narratty-docs/SKILL.md`. Copy it into your agent's skill
directory (for Claude Code, `.claude/skills/narratty-docs/`).
