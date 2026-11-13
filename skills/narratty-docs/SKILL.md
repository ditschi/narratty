---
name: narratty-docs
description: Write a new Markdown doc, or revise an existing one, so that it reads well as documentation AND renders into a narrated terminal video with narratty. Use when the user wants a tutorial, how-to, runbook or concept doc that becomes a video, or asks to make existing docs "narratty-ready".
---

# Writing dual-use docs with narratty

One Markdown file serves readers and viewers. Your job is to keep it **one source of
truth**: plain Markdown that reads well, with as few `<!-- narratty: … -->` comments as
possible. The full rules and their reasons are in `docs/user-guide/dual-use.md` of the
narratty repository; the syntax is in `docs/user-guide/markdown.md`. Read both before
your first edit. Check `narratty --version`: this skill assumes 0.7 or later.

## How narratty reads a doc

- The paragraph directly before a block is its lead-in, spoken **while** the command is
  typed and runs (or before it, with `say: before`).
- A paragraph after a block is spoken in the next scene, with the output still on screen.
- `console` blocks run `$` lines and compare the rest as output. Other languages need a
  `title` (written as a file) or `narratty="show"` (code slide); otherwise they are left
  out and `validate` warns.
- Tables need a `table`/`slide` comment. Mermaid blocks become slides; `focus` comments
  walk flowchart nodes and sequence participants. Images become slides titled with
  their alt text.
- Warning-type admonitions speak their type and title; footnote markers and task-list
  boxes are not spoken.

## Workflow

1. **Inventory.** Run `narratty validate <doc>` and treat every warning as a to-do
   item. Then `narratty check <doc>` (container runtime) and
   `narratty plan --sources <doc>`. List blocks left out, commands that hang or need the
   host, placeholders, tools missing from the image (exit 127).
2. **Decide per block** (run / `instead` / `until` / `lines` / `no-run` / `show` / skip in
   video) and write the decision down before editing.
3. **Edit for both audiences**, in this order of preference:
   1. Change plain Markdown so it works for both (label a fence, shorten a lead-in and end
      it with ":", move an explanation after its block, replace "below" with "next").
   2. Use a construct narratty understands (heading, table + `table` comment, mermaid +
      `focus`, `narratty="show"`).
   3. Use a declarative comment next to the block (`run {…}`, `pause`, `clear`, `hold`).
   4. Only then `hidden` or `skip` + `say`.
4. **Configure once** in the `spec` comment: `clear_on: 2`, `say: before` for tutorials,
   `sections: {exclude: [...]}`, `environment` for tools, `sandbox.env` for variables.
5. **Verify**: `validate` (no warnings left, or each one justified), `check` (expected
   numbers of commands run and shown only, all passing), `plan --sources`.
6. **Build and look**: `narratty build`, extract a frame at each section change, after
   each slide and at each `no-run`/`instead` step, and read the `.srt`.
7. **Report** what you changed for readers (visible text) separately from video-only
   additions (comments, attributes), so the human can review the parallel world.

## Rules (short form)

- Lead-in: 1–2 sentences ending with ":". Explanations of output go after the block.
- No "above", "below", "click here"; reword instead of `skip` + `say`.
- Every shell fence is `console` with `$` prompts and real output; volatile parts → `...`.
- Never change a reader's command for the video: `until` for `tail -f`/servers,
  `lines` for long output, `instead` for installs and clones that can't run in the demo.
- Expected failures really fail and carry `expect-failure`.
- Background jobs redirect their output (`cmd > log 2>&1 &`).
- Placeholders are `$VARS`; values come from `sandbox.env` / `env_passthrough`.
- `no-run` for `sudo`, editors, `open`; say in the text that the step is shown only.
- Snippets that aren't files: `narratty="show"`, never an invented `title`.
- Keep slides up for their conclusion with `hold`; clear with `clear_on`, not hidden `clear`.
- Add terms TTS mispronounces to `tts.lexicon` (`narratty lexicon check`), never respell
  them in the text.
- Keep FAQ/troubleshooting out of the video with `sections: {exclude: [...]}`.

## Don'ts

- Don't run `check --runtime native` on a doc with `hidden` blocks you haven't read:
  they run on the user's machine. Never write a hidden command that uses `--global` or
  touches `$HOME`.
- Don't duplicate a paragraph as a `say` just to reword it slightly; fix the paragraph.
- Don't keep pre-0.7 workarounds (`say Warning!`, footnote `skip` + `say`, `| head` for
  the video, hidden `clear`); they double up with the new defaults.
- Don't build before `check` passes; a build takes minutes, `check` seconds.
