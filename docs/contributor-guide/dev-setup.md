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
| `nox -s docs_check` | `narratty check` on the pages in `CHECKED_DOCS` (`noxfile.py`): their commands run natively, in a copy of the repository, and must print what the page shows |

The video on the Markdown input page is rendered in CI and not committed; to see it
in `mkdocs serve`, render it with `examples/render-ci-videos.sh`. Pull requests that
touch docs, examples or code upload it as the `docs-videos` artifact.

CI renders these videos in the published `ghcr.io/ditschi/narratty:edge` image with
the checkout's wheel installed on top (`docker/render.Dockerfile`). Python changes show
up in a pull request's videos and docs preview; changes to the `Dockerfile` or its
system dependencies do not, until they are merged and `edge` is rebuilt. Check those
by building the image locally and rendering with
`examples/render-ci-videos.sh --runtime docker --image <tag>`.

## Commits

Commits and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat: …`, `fix: …`, `docs: …`). PRs are squash-merged, so the PR title becomes the commit.

## Logo

`docs/assets/` holds the logo files:

| File | Use |
|---|---|
| `logo-source.svg` | Editable source (text as `<text>`) |
| `logo.svg`, `logo.png` | Full logo, text converted to paths (README, docs home) |
| `icon.svg`, `icon.png` | Square mark (docs header, avatars) |
| `favicon.ico` | Docs favicon (16, 32, 48 px) |
| `social-preview.png` | GitHub social preview (1280x640, set in the repository settings) |

After editing `logo-source.svg`, convert the text to paths (JetBrains Mono NL
ExtraBold, Bold for the output line) and re-export the PNGs.
