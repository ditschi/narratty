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

- Before every commit run `nox -s code-health -- --changed` (add `--json` to parse it). Every
  changed file must score at least 9.5 and must not get worse; the repository score must not
  drop below `code-health-baseline.json`. Pre-commit and CI enforce the same gate.
- Fix smells by refactoring, keeping behaviour and tests unchanged; do not suppress them.
  A suppression needs a reason: `# code-health: ignore[<smell>] <why>`.
- After raising scores, run `nox -s code-health -- --update-baseline` and commit the baseline.
- Thresholds and weights are in `code-health.toml`, explained in
  `docs/contributor-guide/code-health.md`.

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
