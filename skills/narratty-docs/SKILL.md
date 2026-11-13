---
name: narratty-docs
description: Write a new Markdown doc, or revise an existing one, so that it reads well as documentation AND renders into a narrated terminal video with narratty. Use when the user wants a tutorial, how-to, runbook or concept doc that becomes a video, or asks to make existing docs "narratty-ready".
---

# Writing dual-use docs with narratty

One Markdown file serves readers and viewers. Your job is to keep it **one source of
truth**: plain Markdown that reads well, with as few `<!-- narratty: … -->` comments as
possible. The full rules and their reasons are in `docs/user-guide/dual-use.md` of the
narratty repository; the syntax is in `docs/user-guide/markdown.md`. Read both before
your first edit.

## How narratty reads a doc

- Paragraphs collect until a code block runs; they are the narration of that block's
  scene, spoken **while** the command is typed and runs.
- A paragraph after a block is spoken in the next scene, with the output still on screen.
- `console` blocks run `$` lines and compare the rest as output. Unlabelled fences, and
  other languages without a `title`, are left out silently.
- Tables are left out unless a `table`/`slide` comment precedes them. Mermaid blocks
  become slides; `focus` comments walk flowchart nodes.
- Admonition titles, footnote markers and task-list boxes are not handled: titles are
  dropped, `[^1]` and `[ ]` are read literally.

## Workflow

1. **Inventory.** For an existing doc: run `narratty check <doc>` and
   `narratty plan --sources <doc>`. List every block that is left out, every
   command that would hang or needs the host, every placeholder.
2. **Decide per block** (run / show only / hidden setup / skip in video) and write the
   decision down before editing.
3. **Edit for both audiences**, in this order of preference:
   1. Change plain Markdown so it works for both (label a fence, shorten a lead-in,
      move an explanation after its block, replace "below" with "next").
   2. Use a Markdown construct narratty understands (heading, table + `table` comment,
      mermaid + `focus`).
   3. Only then add a comment (`hidden`, `skip` + `say`, `no-run`, `pause`).
4. **Verify**: `narratty validate`, `narratty check` (must report the expected number of
   commands, all passing), `narratty plan --sources`.
5. **Build and look**: `narratty build`, then extract a frame at each section change and
   after each slide and inspect it. Read the `.srt` next to the video for things that
   were spoken wrongly.
6. **Report** what you changed for readers (visible text) separately from video-only
   additions (comments), so the human can review the parallel world.

## Rules (short form)

- Lead-in before a command: 1–2 sentences, ending with ":".
- Explanations of output go after the block.
- No "above", "below", "click", "press"; no footnotes, task lists or inline images in
  narrated sections. Say callout types ("Be careful:") in the text.
- Every shell fence is `console` with `$` prompts and real output; volatile output → `...`.
- Commands must terminate: no `tail -f`, foreground servers or interactive prompts.
  Use `| sed '/ready/q'`, `| head`, or `cmd > log 2>&1 &`.
- Make output end with a newline (`curl -s -w '\n'`).
- Expected failures really fail and carry `expect-failure`.
- Placeholders are `$VARS`; secrets come from `sandbox.env_passthrough`, never from a
  `hidden` comment.
- One `hidden` setup block at the top of the first section, or an `environment` in
  the `spec` comment, instead of scattered setup.
- `no-run` for host-only commands (`sudo`, editors, `open`); `skip` + one-sentence `say`
  for steps the demo already did.
- Give blocks you override an id (`{#install}`); put overrides in the top `spec` comment.
- Add terms TTS mispronounces to `tts.lexicon` (`narratty lexicon check`), never respell
  them in the text.
- Keep FAQ/troubleshooting out of the video with `sections`; keep them in the doc.

## Don'ts

- Don't duplicate a paragraph as a `say` just to reword it slightly; fix the paragraph.
- Don't change a command for readers into something they wouldn't type, unless it is
  needed to terminate; then explain it in one clause ("stop at the first ready line").
- Don't build before `check` passes; a build takes minutes, `check` seconds.
