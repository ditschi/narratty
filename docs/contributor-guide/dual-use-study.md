# Dual-use usability study (2026-11)

Four authors wrote docs with narratty 0.6.2.dev (PR #59 image) and turned them into
videos, each with at least two build iterations, learning only from the user guide:

| Persona | Doc | Main topics |
|---|---|---|
| CLI maintainer | Getting-started tutorial | install, config file, failing command, tables |
| Tech lead | Architecture overview | Mermaid walkthroughs, tables, callouts, shown-only code |
| Contributor | Retrofit of an existing CONTRIBUTING guide | unlabelled fences, numbered steps, FAQ, host-only steps |
| SRE | Troubleshooting runbook | secrets, background processes, long output, timing control |

The author rules that came out of it are in [Docs for reading and listening](../user-guide/dual-use.md).
This page records what works, what doesn't and what to build next.

## What works

- **`narratty check`** was the most valued feature. It found real doc bugs: a
  "failing" example that succeeded, and output that had drifted.
- **`table` comments** with `say` templates. Row-by-row highlighting synced to the
  voice works well for comparisons and decision tables ("If you see X, do Y").
- **Mermaid `focus` walkthroughs** on flowcharts: one paragraph per node, highlight
  exactly in sync.
- **Placeholders as `$VARS`**, with a clear error and hint for `<placeholder>`.
- **`expect-failure`**: the error stays on screen while the next paragraph explains it.
- **`lexicon check`** flags acronyms before the first build.

## Parallel worlds: where authors had to say things twice

| Situation | Today's workaround | Cost |
|---|---|---|
| Reader command can't run in the video (`pip install`, `git clone`) | `no-run` (visible `^C`) plus hidden substitute plus hidden `clear`, or `skip` + `say` | High; nothing links shown and run command |
| Shown-only code (JSON response, config excerpt) | Invent a `title` so it's shown as a file | Video claims a file exists |
| Footnotes, "Note:" titles, warnings | `skip` + `say` with the reworded sentence | Pure duplication |
| Table lead sentence spoken before the slide | `skip` it for the video | Readers and viewers get different text |
| Excluding the FAQ loses the H1 intro | Re-add the intro as `say` | Duplication |
| Timing per block | `{#id}` in the doc + `overrides` entry elsewhere | Two places per block |
| Long or never-ending output | Change the reader's command (`\| head`, `\| sed '/x/q'`) | Readers copy unusual commands |
| Diagram node ids | Repeated in every `focus` comment, unchecked by `validate` | Typos only show at build time |

## Ordering and timing: what authors expected

Today narration starts with the scene, so "paragraph, then block" means *talk while
typing and running*. Authors expected three distinct modes and a way to pick one per
block without leaving the Markdown:

- **explain, then run**: the voice finishes, then typing starts;
- **run, then explain**: the paragraph after the block, in the same scene;
- **talk while running**: today's default, useful for slow commands.

The existing controls (`before: [{hold: auto}]`, `narration_start: after_actions`) live
in `overrides`, and linear audio/video synchronization shifts them by 1–3 s. Real
command durations are not in the plan, so slow commands lengthen scenes.

Other surprises:

- The screen never clears between sections, except after a hidden scene. Later
  narration plays over stale output, and the screen state depends on whether a file
  block happened to appear.
- A heading badge for a section that starts with a hidden block appears late.
- The paragraph after a slide plays over the terminal; authors wanted the slide to stay.
- Items of an ordered list are merged into the next command's narration.

## Bugs found

| Severity | Bug |
|---|---|
| Major | Snapshot `git clone` fails with "Invalid cross-device link" when the doc and the cache are on different filesystems; no hint. Fall back to `--no-hardlinks`. |
| Major | `clear` inside a `hidden` block shifts exit-code attribution by one scene (`exits.log` gets an extra entry). |
| Major | Output without a trailing newline, or late output from a background job, times out waiting for the prompt; the error names no scene or line and the hint is about a pattern. |
| Major | `plan --draft` and `check` pull the 2 GB `edge` image silently; `docker: pull access denied` is not wrapped in a narratty error. |
| Major | The `hidden` comment copies secrets into `exits.log` and `~/.cache/narratty/compiled/`. |
| Minor | Drift hint says a command "took longer" when the video is *shorter* (dropped frames under load). |
| Minor | Build prints the container path (`/out/x.mp4`) instead of the host path. |
| Minor | "capturing browser views" is logged for docs without browser views. |
| Minor | `- [ ]` is read as "[ ]"; footnote markers and definitions are read literally. |
| Minor | `plan --sources` says "left out (no title)" for an unlabelled fence (it has no language); badges are not listed. |
| Minor | Every validate error ends with the hint "Run `narratty schema`", even for YAML quoting errors in comments. |
| Minor | `focus` on sequence-diagram participants is unsupported; `validate` doesn't check focus ids against the diagram. |
| Minor | `--runtime native check` still starts the environment container. |

## Roadmap proposals

Ordered by the number of parallel worlds each removes.

### 1. Per-block timing in the Markdown

A comment right before a block, so no `overrides` entry is needed:

```markdown
<!-- narratty: run {after: say} -->     explain, then run
<!-- narratty: run {before: say} -->    run, then speak the paragraph after the block
<!-- narratty: run {during: say} -->    default: talk while it runs
```

Pair it with **per-scene alignment** to the recorded scene marks instead of linear
stretching, and measure command durations in `check` to plan with them.

### 2. Show one command, run another

````markdown
```console {narratty="run='pip install -e .'"}
$ pip install tally
```
````

The reader sees the real install, the video runs the substitute without `^C`. It
replaces `no-run` + hidden substitute + hidden `clear`. Make `no-run` clear its line
instead of leaving `^C`.

### 3. Long-running commands

```markdown
<!-- narratty: wait "listening on" {then: C-c, timeout: 30s} -->
```

Applied before the automatic prompt wait, so `tail -f` and foreground servers can stay
in the doc as readers would type them.

### 4. Screen and slide lifetime

- `<!-- narratty: clear -->` and an entry option `clear_on: 2` (clear at each H2).
- `slide {hold: next-heading}` keeps a table or diagram up for the paragraphs after it.
- Speak the lead paragraph directly above a `table`/`slide` comment while the slide is
  shown.

### 5. Better defaults for common Markdown

- Footnotes: drop markers from speech, skip definitions (`footnotes: skip|inline`).
- Task lists: strip `[ ]`/`[x]`; optionally show checklists as a slide.
- Admonitions: speak the type for `warning`/`danger` ("Warning: …"); optionally a
  styled callout slide. Configurable per type (`admonitions: {warning: "Warning: {body}"}`).
- Shown-only code: `{narratty="show"}` (or a default for untitled blocks after a
  paragraph ending in ":") renders a highlighted code slide, no fake file.
- Images: use the alt text as the slide title.
- `sections: {exclude: [troubleshooting]}` and a `skip-rest` comment, keeping the intro.
- On-screen output limit `output {show: 10}` that matches the doc's `...`.

### 6. Authoring help

- **`validate` warnings**: no runnable commands; ignored fences that contain `$ ` lines;
  tables without a comment; output that looks like an error without `expect-failure`;
  `focus` ids not in the diagram (with "did you mean"); spatial words ("above",
  "below") in narrated text.
- **`narratty suggest <doc>`**: proposes the edits of the retrofit checklist as a diff
  and prints a score ("12 blocks run, 3 typed, 9 left out"). The agent skill in
  `skills/narratty-docs/` covers the same ground for agents today.
- **Faster loop**: allow the scene cache with slides and overlays; announce image pulls
  with size; put scene id and Markdown line in every runtime error.

## Round 2 (0.7 features)

The same four authors rebuilt their docs with the features from the roadmap above.

| Measure | Round 1 | Round 2 |
|---|---|---|
| Retrofit of the CONTRIBUTING guide | about 90 min, several fix-up builds | 19 min, first build acceptable |
| Hidden setup commands (tutorial) | 5 | 0 |
| Reader commands changed for the video (runbook) | 3 | 0 |
| YAML `overrides` for timing (runbook) | 3 | 0 |
| Video-only comments, like for like (architecture) | 16, two duplicating text | 9, none duplicating text |
| Narration offset for `say: after` / `during` | drifted 1–3 s | constant 0.7–0.8 s over 110 s under load |

Bugs found in round 2 and fixed before release: lead-ins swallowed by the text after a
`say: after` block, a `show` block or a slide; `say: before` not waiting for the whole
narration; hidden command text in the durations cache; hidden commands touching the real
`$HOME` under `--runtime native` (now refused for `--global`, `~` and `$HOME` unless
`--yes`); `check` counting `no-run` commands as run; inline footnotes placed at the end
of the paragraph; `set +m` breaking duration measurement; containers left running after
an interrupted build; plus lint false positives and YAML-only wording in Markdown hints.

Still open: time spent in `until` waits is not part of the plan; job-control lines
(`[1] 161`) show on screen; a `no-run` command is followed by a fresh prompt; builds take
3–6 minutes, and the scene cache does not apply to docs with slides.
