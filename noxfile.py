"""Nox sessions for narratty.

Uses the uv backend and mirrors repo-env's quality gates
(ruff, mypy, vulture, fawltydeps, pylint duplicate/cyclic checks).
"""

from __future__ import annotations

import os

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

DEFAULT_PYTHON = "3.12"
PYTHON_VERSIONS = ["3.12", "3.13", "3.14"]
PACKAGE = "narratty"
SRC = "src/narratty"


def _env_truthy(name: str) -> bool:
    """Return True when ``name`` is set to a common truthy string."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_ci() -> bool:
    """Return True when running in CI (``NOX_LOCAL=1`` / ``NOX_CI=1`` force either way)."""
    if _env_truthy("NOX_LOCAL"):
        return False
    return any(_env_truthy(name) for name in ("NOX_CI", "CI", "GITHUB_ACTIONS", "GITLAB_CI"))


# Sessions run by default. Locally we also run `format` before `lint`.
_CI_DEFAULT = [
    "check_syntax",
    "tests",
    "lint",
    "check_types",
    "necessary_imports",
    "dead_code",
    "duplicates",
    "cyclic_imports",
]
nox.options.sessions = _CI_DEFAULT if is_ci() else (["format"] + _CI_DEFAULT)


@nox.session(python=PYTHON_VERSIONS, tags=["unit", "tests"])
def tests(session: nox.Session) -> None:
    """Run unit tests with coverage and xdist (all supported Python versions)."""
    session.install("-e", ".[test]")
    session.run(
        "pytest",
        f"--cov={PACKAGE}",
        "--cov-report=term-missing",
        "-n",
        "auto",
        "tests/unit/",
        *session.posargs,
    )


@nox.session(python=DEFAULT_PYTHON, tags=["integration"])
def integration(session: nox.Session) -> None:
    """Run real TTS engines, VHS and ffmpeg (downloads voices on first run)."""
    session.install("-e", ".[test,kokoro]")
    session.run("pytest", "-m", "integration", "tests/integration/", *session.posargs)


@nox.session(python=False, tags=["agent"])
def agent(session: nox.Session) -> None:
    """Vet and test narratty-agent, the Go helper for project environments (needs Go)."""
    with session.chdir("agent"):
        session.run("go", "vet", "./...", external=True)
        session.run("go", "test", "./...", external=True)


@nox.session(python=DEFAULT_PYTHON, tags=["performance"])
def performance(session: nox.Session) -> None:
    """Check CLI cold-start latency budgets (help and shell completion)."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "performance", "tests/performance/", *session.posargs)


@nox.session(python=DEFAULT_PYTHON, tags=["docs"])
def docs(session: nox.Session) -> None:
    """Build documentation with mkdocs --strict (zero warnings)."""
    session.env["NO_MKDOCS_2_WARNING"] = "1"
    session.install("-e", ".[docs]")
    session.run("mkdocs", "build", "--strict", *session.posargs)


@nox.session(python=DEFAULT_PYTHON, tags=["docs"])
def docs_serve(session: nox.Session) -> None:
    """Serve docs locally with live reload (http://127.0.0.1:8000)."""
    session.env["NO_MKDOCS_2_WARNING"] = "1"
    session.install("-e", ".[docs]")
    session.run("mkdocs", "serve", *session.posargs)


@nox.session(python=DEFAULT_PYTHON)
def check_syntax(session: nox.Session) -> None:
    """Byte-compile all sources to catch syntax errors fast."""
    session.run("python", "-m", "compileall", "-q", SRC, external=False)


@nox.session(python=DEFAULT_PYTHON)
def check_types(session: nox.Session) -> None:
    """Static type checking with mypy."""
    session.install("-e", ".[type-check]")
    session.run("mypy", "--package", PACKAGE)


@nox.session(python=DEFAULT_PYTHON, tags=["quality", "lint"])
def lint(session: nox.Session) -> None:
    """Run ruff check and ruff format --check."""
    session.install("-e", ".[lint]")
    session.run("ruff", "check", SRC, "tests", "noxfile.py")
    session.run("ruff", "format", "--check", SRC, "tests", "noxfile.py")


@nox.session(python=DEFAULT_PYTHON, tags=["quality", "format"])
def format(session: nox.Session) -> None:  # noqa: A001 - keep conventional session name
    """Auto-format with ruff (local only)."""
    session.install("-e", ".[lint]")
    session.run("ruff", "check", "--fix", SRC, "tests", "noxfile.py")
    session.run("ruff", "format", SRC, "tests", "noxfile.py")


@nox.session(python=DEFAULT_PYTHON)
def necessary_imports(session: nox.Session) -> None:
    """Detect undeclared/unused dependencies with fawltydeps."""
    session.install("-e", ".[code-quality]")
    session.run(
        "fawltydeps",
        "--detailed",
        "--code",
        SRC,
        "--deps",
        "pyproject.toml",
        "--deps-parser-choice",
        "pyproject.toml",
        "--ignore-unused",
        "piper-tts",  # run as a subprocess (`python -m piper`), never imported
        "commitizen",
        "fawltydeps",
        "mike",
        "mkdocs",
        "mkdocs-material",
        "mkdocstrings",
        "mypy",
        "nox",
        "pre-commit",
        "pylint",
        "pytest",
        "pytest-cov",
        "pytest-xdist",
        "ruff",
        "vulture",
    )


@nox.session(python=DEFAULT_PYTHON)
def dead_code(session: nox.Session) -> None:
    """Detect dead code with vulture."""
    session.install("-e", ".[code-quality]")
    session.run("vulture")


@nox.session(python=DEFAULT_PYTHON)
def duplicates(session: nox.Session) -> None:
    """Detect duplicate code (pylint R0801)."""
    session.install("-e", ".[code-quality]")
    session.run("pylint", "--disable=all", "--enable=R0801", "--min-similarity-lines=6", SRC)


@nox.session(python=DEFAULT_PYTHON)
def cyclic_imports(session: nox.Session) -> None:
    """Detect cyclic imports (pylint R0401)."""
    session.install("-e", ".[code-quality]")
    session.run("pylint", "--disable=all", "--enable=R0401", SRC)
