# AGENTS.md

`narratty` is a Python CLI (command and import package `narratty`) that turns a
`.narratty.yaml` spec into a narrated terminal video. The design and milestones live in
`docs/contributor-guide/design.md`; read it before adding features.

## Tooling

- **uv** manages the environment (`uv sync --extra dev` creates `.venv`), **nox** runs the
  quality gates. `noxfile.py` is the authoritative command list.
- Lint and format: ruff only (`nox -s lint`, `nox -s format`). Types: mypy (`nox -s check_types`).
- Unit tests: `nox -s tests` or `.venv/bin/pytest`. Performance budgets are marked
  `performance` and deselected by default; run them with `nox -s performance`.
- Docs: `nox -s docs` (mkdocs `--strict`, zero warnings). `nox -s docs_check` runs the
  commands of the pages in `CHECKED_DOCS` and compares their output with the page; a page
  joins the list once its commands only touch the workspace copy (mark others `no-run`).

## Code health

- Before every commit run `nox -s code-health -- delta` (aihealth; `--format json` or
  `--format markdown` to parse it) and fix what it reports. Nothing may get worse, new files
  may have no smell; the target is 10 (9.5 at least; the gate enforces only "no
  degradation"). Pre-commit (`delta --staged`) and CI (delta from the
  merge base plus component scores) enforce it.
- Fix smells by refactoring, keeping behaviour and tests unchanged; do not suppress them.
  A suppression is file-wide and needs a reason after ` -- `:
  `# aihealth: disable=<smell> -- <why>`.
- Always pass `--config .aihealth.toml` when calling aihealth directly (the nox session does).
  The profile lives only there; aihealth is pinned only in the `code-health` dependency group.
- ruff has no structure rules (`C90`); aihealth is the one source for structure smells.
- The earlier own checker (`tools/code_health/`, `nox -s code-health-own`) is only a
  cross-check; do not extend it.
- The project skills `py-complexity` and `py-code-health` (`.claude/skills/`, pinned in
  `skills-lock.json`) supply refactoring patterns. Measure with aihealth, not with the tools
  those skills name: do not add radon, lizard, xenon or wily, and skip their
  `py-quality-setup` step, which changes Claude settings.
- Details: `docs/contributor-guide/code-health.md`.

## Agent skills

Project skills live in `.claude/skills/`, pinned in `skills-lock.json` (`npx skills add ... -a claude-code`).

- `systematic-debugging` and `verification-before-completion` (obra/superpowers): follow them.
  Verification here means the nox sessions above with their output, not claims. Ignore their
  JavaScript bits: `find-polluter.sh` runs `npm test` (bisect with pytest instead, one test file at a time:
  `.venv/bin/pytest <file>`), and the `superpowers:test-driven-development` skill
  they mention is not installed.
- `typer` (fastapi/typer, official): use its patterns (`Annotated` declarations, no Click
  extensions) for new and changed commands. Do not migrate untouched commands from the
  `typer.Option(...)` default style in unrelated changes; dependencies go into
  `pyproject.toml` and `uv sync`, not `pip install`.
- Third-party skill files are excluded from aihealth (`.aihealth.toml`).

## Conventions

- One module per subcommand under `src/narratty/cli/commands/`. Import heavy dependencies
  inside the command function so `--help` and shell completion stay under their budgets.
- Errors are `NarrattyError` subclasses carrying an `ExitCode` and an optional `hint`;
  never renumber `ExitCode`.
- Data goes to stdout, logs and errors to stderr (`narratty.ui.console`).
- Commits and PR titles follow Conventional Commits.
- Spec changes: additive keys keep `version: 1` and get "(since X.Y)" in `docs/user-guide/spec.md`;
  only breaking changes get a new spec version. See `docs/contributor-guide/release-process.md`.

## Gotchas

- The version comes from git tags via hatch-vcs; shallow clones without tags report
  `0.1.devN`. CI checks out with `fetch-depth: 0`.
- `nox` without `NOX_CI=1` runs `format` first, which edits files.
