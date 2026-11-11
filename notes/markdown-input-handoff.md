# Handoff: Markdown as video input

Status on 2026-11-11: design agreed, steps 1 and 2 done. The design is the section
"Markdown input (planned)" in `docs/contributor-guide/design.md`; read it and
`AGENTS.md` first. Treat the decisions there as settled unless the user reopens them.

## Open points
Settled on 2026-11-11 and written into the design (table "How a doc becomes scenes",
the `tabs` key, "narratty in the recorded shell"). Nothing open before implementing.

## Implementation order
1. **Model and loader** (`src/narratty/spec/`): a `markdown:` scene entry in the raw
   document only; the loader expands it into plain `Scene`s, so timeline, render, cache
   and exit checks stay unchanged. `Issue` gets a file next to its line. Regenerate
   `schema/v1.json`; stays `version: 1`.
2. **Parser**: markdown-it-py (already installed through Rich) plus mdit-py-plugins
   `admon` (a new dependency), a small rule for `=== "tab"` and snippet inclusion.
   Golden tests: Markdown fixture → expanded YAML, using this repo's `docs/` as the
   corpus.
3. **Commands**: split `bash`/`sh` blocks by complete shell syntax, add
   `wait: {prompt: true}` after each command, drop trailing `# …` comments, and fail on
   `<angle>` placeholders.
4. **Doc comments and fence attributes**: `skip`, `say`, `overlay`, `hidden`;
   `{#id narratty="no-run hidden expect-failure" title="…"}`; entry `defaults` and
   `overrides`.
5. **Overlays**: new `chapter` default (`keep: false`, `duration_ms: 3s`, with a
   changelog note), built-in `heading-1`… `heading-4`, `breadcrumb` and `file` styles,
   and the renderer merging identical overlays at the same position in consecutive
   scenes.
6. **Tooling**: `narratty plan --sources`, `narratty compile`; sandboxed runs pass the
   expanded spec to the container, which only mounts the spec file.
7. **Docs**:
   - "(since X.Y)" entries in `docs/user-guide/spec.md`;
   - `docs/user-guide/markdown.md` written as the video's own source, with
     `examples/markdown/markdown.narratty.yaml` and a line in `examples/render-docs.sh`;
   - the copy-button CSS from the design as `extra_css`;
   - a nav entry in `mkdocs.yml`.

## Step 1 (done)
- `MarkdownEntry`, `SceneDefaults`, `BlockOverride`, `HeadingOverlays` and the top-level
  `narration` in `spec/model.py`; `Spec.scenes` stays `list[Scene]`.
- `parse_document` returns `Document(spec, data, origins)`: each scene's index in the
  YAML, or the `ExpandedScene` (file, line) it came from. Errors in expanded scenes point
  at the Markdown line; hints skip them.
- `spec/markdown/__init__.py:expand_entry` is the hook the loader calls; loader tests
  replace it with a fake.
- The schema picks `MarkdownEntry` or `Scene` with `if`/`then`/`else` on the `markdown`
  key, so editors keep precise errors for scenes.
- `tests/unit/test_diff.py` fails locally with a delta git pager; unrelated, also on main.

## Step 2 (done)
- `spec/markdown/source.py`: snippets (`path[:start[:end]]`, nested, base from the
  nearest `mkdocs.yml`, else the git root) and content tabs, on lines that keep their
  file and line number. Unpicked tabs become blank lines, so numbering stays.
- `spec/markdown/parse.py`: markdown-it-py + `admon` to `Heading`, `Text`, `Code`,
  `Comment` blocks. Slugs replicate `pymdownx.slugs` plus the TOC's `_1` suffixes.
  `Code.id`/`title`/`options` and `Comment` are parsed but not used yet (step 4).
- `spec/markdown/scenes.py`: section selection (`EntryError` is positioned in the YAML),
  narration joining, ids `<prefix>-<section>-<n>` (`<prefix>-<n>` before the first
  heading; `n` counts generated ids only) and entry `defaults`.
- Already in step 2: `wait: {prompt: true}` after every command and `console` parsing.
  Left for step 3: `bash`/`sh` blocks are split per line (comments skipped, `\`
  continuations joined) as a stand-in; titled non-shell blocks are skipped instead of
  written as files; multi-line commands (`> ` lines, `\`) still need checking in VHS.
- Tests: `tests/unit/spec/test_markdown.py` with golden fixtures in
  `tests/unit/spec/markdown/` (regenerate with `NARRATTY_UPDATE_GOLDEN=1`) and a test
  that every page under `docs/` expands to a valid spec.

## Verification already done
Fence syntax, HTML comments and the copy button were checked against this repo's mkdocs
config, GitHub's Markdown API and markdown-it-py 4.2. The results are in the design under
"Verified rendering". Re-check only if the mkdocs extensions change.

## Ground rules
- Quality gates: `nox -s lint check_types tests docs` (or `uv run` with the extras).
- Conventional Commits; never renumber `ExitCode`; heavy imports inside commands.
- Delete this note once the open points are settled and the work is tracked elsewhere.
