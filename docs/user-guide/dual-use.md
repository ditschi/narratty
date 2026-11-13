# Docs for reading and listening

A narratty doc serves two audiences from one file: someone **reading** it in a browser
and someone **watching** the video. The goal is one source of truth: plain Markdown that
reads well, with as few `<!-- narratty: … -->` comments as possible. Every comment is a
"parallel world" that readers don't see and that can drift from the text around it.

This page collects the rules that keep the two in step. They come from two rounds of a
usability study in which authors wrote tutorials, architecture overviews and runbooks
with narratty and retrofitted existing guides to it.

## The scene model in one paragraph

The doc is read top to bottom. The paragraph directly before a block is its lead-in and
is spoken while that block runs; by default **narration and typing start together**. A
paragraph after a block is spoken in the next scene, while the output is still on
screen. A `run` comment before a block changes the order per block, see
[Choosing who goes first](#choosing-who-goes-first-voice-or-command). See also
[How a doc becomes scenes](markdown.md#how-a-doc-becomes-scenes).

## Rules

### Write for the ear first, then check the page

1. **Keep the lead-in short and end it with a colon.** One or two sentences that say
   *what* the command does: "Check that it works:". The colon also tells narratty the
   paragraph belongs to the next block or slide, and listeners that something follows.
2. **Explain output after the block.** A paragraph after a block is spoken while the
   output is on screen. That is the natural "run, then explain".
3. **Avoid spatial and UI words.** "Above", "below", "the command below" and "click here"
   make no sense when spoken; `narratty validate` flags them. Reword ("next", "this
   command", "the output shows") rather than adding a `skip` + `say` pair.
4. **Let callouts speak for themselves.** Warning, caution, danger and important
   admonitions start with their type and title ("Warning: Cache keys. …"). Note and tip
   are read like text. Change it per type with the entry key `admonitions`.
5. **Footnotes and task lists are fine.** Markers and checkboxes are not spoken;
   footnotes are skipped, or spoken after their sentence with `footnotes: inline`.
6. **Spell out what TTS gets wrong in the lexicon, not in the text.** Run
   `narratty lexicon check` and add terms such as `JWT` or `config.yaml` to
   `tts.lexicon` in the `spec` comment. The text stays correct for readers.

### Keep the reader's commands as readers type them

7. **Label every shell fence `console`,** with `$` prompts and the real output. Volatile
   parts become `...`, also within a line (`Python 3...`).
8. **Never rewrite a command for the video.** Use a `run` comment instead:
   - `until: "listening on"` for `tail -f` and servers: wait for the text, then Ctrl+C;
   - `lines: 10` to shorten long output on screen (`check` still compares the full output);
   - `instead: "pip install -e ."` when the reader's command can't run in the demo
     (offline install, a clone of their fork).
9. **Make expected failures fail for real** and mark them `expect-failure`. `check`
   verifies both the exit code and the output.
10. **Redirect the output of background jobs** (`app > app.log 2>&1 &`). Output that
    arrives after the prompt can make a build time out; `validate` warns about a bare `&`.
11. **Write placeholders as environment variables** (`$TOKEN`, not `<token>`). Put
    values in `sandbox.env` or `sandbox.env_passthrough`, never in a `hidden` block.
12. **Use `no-run` for host-only commands** (`sudo`, editors, `open`). The command stays
    on screen without being run; say in the text that it is shown, or add an `overlay`.

### Keep the parallel world small

13. **Prefer a Markdown construct over a comment.** A table with a `table` comment, a
    diagram with `focus` comments and a heading per step read well on the page. A `say`
    that replaces a paragraph does not.
14. **Show snippets that aren't project files with `narratty="show"`.** A JSON response or
    a config excerpt becomes a highlighted code slide; don't invent a `title` for it.
15. **Let slides stay for their conclusion** with `hold: next-block` or
    `hold: next-heading` on the `slide` or `table` comment.
16. **Clear the screen with `clear_on: 2`** in the `spec` comment instead of hidden
    `clear` commands.
17. **Keep setup out of the doc.** Toolchains go into `environment`, variables and git
    identity into `sandbox.env`. If a `hidden` block is unavoidable, keep it to one at the
    top of the first section, and never let it touch `$HOME` or use `--global`: under
    `--runtime native` it runs on your machine.
18. **Pick sections, don't skip paragraphs.** `sections: {exclude: [troubleshooting]}`
    keeps the intro; `<!-- narratty: skip-rest -->` leaves out the rest of a section.
19. **Remove old workarounds when you upgrade.** A `say Warning!` or a footnote
    `skip` + `say` from before 0.7 now doubles up with the new defaults.

### Check before you build

20. **Run `narratty validate`, then `narratty check`, after every edit.** Treat each
    warning as a to-do item. `check` runs the commands as the video would and reports
    "N commands ran, M shown only"; nothing ran means nothing is wired up.
21. **Run `narratty plan --sources`** to see what each Markdown element became and why
    something was left out. Run `check` first: `plan` then uses the measured command
    durations.
22. **Look at the video at section changes** and after slides. Extract frames with
    `ffmpeg -ss <t> -i out.mp4 -frames:v 1 f.png`, and read the `.srt`.

## What each element becomes

| Element | On the page | In the video | Recommendation |
|---|---|---|---|
| Heading | Structure | Chapter overlay (`heading_overlays`); the H1 card stays during the intro | One heading per step; it also scopes `sections` |
| Paragraph | Text | Lead-in of the next block, or the scene after a block | Short before a block, explanations after it |
| `console` block | Command and output | Typed, run, output compared by `check` | The default for shell examples |
| `bash` block | Script | Each command runs; output not compared | Scripts readers copy as a whole |
| Code with `title` | File listing | Written hidden, shown with `cat` and a file overlay | Config files the demo needs |
| Code with `narratty="show"` | Listing | Highlighted code slide | Responses, excerpts, examples |
| Code without either | Listing | Left out (`validate` warns) | Add `show` or a `title` |
| Table | Table | Left out; slide with a `table` or `slide` comment | Decisions and comparisons: `table {say: "If {A}, {B}."}` |
| `mermaid` | Diagram | Slide; `focus` comments walk flowchart nodes and sequence participants | One short paragraph per node |
| Image on its own line | Image | Slide titled with the alt text | Write a meaningful alt text |
| Admonition | Callout | Warnings say their type and title | Nothing extra needed |
| Collapsed block, `<details>` | Hidden until opened | Left out | Reader-only background, FAQ |
| Content tabs | Tabs | First tab, or the one the entry names | Keep tabs equivalent |
| Footnote, task list | Rendered | Markers not spoken | Fine |
| Inline code, links | Formatted | Plain text, lexicon applies | Avoid bare URLs |

## Choosing who goes first: voice or command

| You want | Write before the block | What happens |
|---|---|---|
| Talk while it runs | nothing | Default (`say: during`) |
| Explain, then run | `<!-- narratty: run {say: before} -->` | Typing starts once the lead-in is spoken |
| Run, then explain in the same scene | `<!-- narratty: run {say: after} -->` | The text after the block is spoken once the commands are done |
| Let the output sink in | `<!-- narratty: pause 2s -->` after the block | A silent pause |

The same keys fit in the block's attributes (`narratty="say=before lines=10"`), and the
entry key `say: before` makes "explain, then run" the default for a whole tutorial.
With `say: after`, keep the lead-in very short: it is spoken over an idle prompt.

## Retrofitting an existing guide

1. Run `narratty validate` on the guide as it is. Typical result: "no command runs" and
   one warning per unlabelled fence with `$` lines.
2. Label shell fences `console`; replace volatile output with `...`.
3. Split blocks so that commands with different needs (run, `no-run`, `instead`) are in
   separate blocks, and turn commands that only appear inline in a step ("run
   `make lint`") into blocks. Both help readers too.
4. Mark host-only steps `no-run`; use `instead` for steps that need another command in
   the demo, `until` for commands that don't end.
5. Make sure every section's first block has a lead-in, or it plays silent.
6. Set `clear_on: 2`, pick the sections with `sections: {exclude: [...]}`, and add
   `environment.packages` when `check` reports a missing tool (exit 127).
7. Add a `table` comment to tables the video needs and `focus` comments to diagrams.
8. Run `check`, then `build`, and look at the frames at each section change.

Expect to change about a sixth of the reader-visible text, and most of those changes
improve the written guide as well.

## Agents

The repository ships an agent skill that applies these rules when writing or
retrofitting a doc: `skills/narratty-docs/SKILL.md`. Copy it into your agent's skill
directory (for Claude Code, `.claude/skills/narratty-docs/`).
