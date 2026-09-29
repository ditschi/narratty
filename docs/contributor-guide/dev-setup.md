# Development setup

Tooling is managed with [uv](https://docs.astral.sh/uv/) and [nox](https://nox.thea.codes/).

```bash
uv sync --extra dev          # .venv with narratty and all dev tools
uv run pre-commit install    # ruff, mypy, codespell, commit-msg check
```

## Quality gates

| Command | What it runs |
|---|---|
| `nox` | Everything below (plus `format` locally; set `NOX_CI=1` to skip it) |
| `nox -s tests` | Unit tests on Python 3.12–3.14 with coverage |
| `nox -s lint` | `ruff check` + `ruff format --check` |
| `nox -s check_types` | mypy (strict settings in `mypy.ini`) |
| `nox -s necessary_imports` | fawltydeps: undeclared or unused dependencies |
| `nox -s dead_code` | vulture |
| `nox -s duplicates` / `cyclic_imports` | pylint R0801 / R0401 |
| `nox -s performance` | Cold-start budgets for `--help` and shell completion |
| `nox -s docs` | `mkdocs build --strict` |

## Commits

Commits and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat: …`, `fix: …`, `docs: …`). PRs are squash-merged, so the PR title becomes the commit.
