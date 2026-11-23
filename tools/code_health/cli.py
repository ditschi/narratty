"""code-health: score Python files 1-10 (CodeScene-style), print them and run the gate."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from . import config as config_module
from .config import Config
from .gate import Baseline, Gate, changed_paths, default_base, text_at, updated_baseline
from .model import FileReport
from .report import as_json, as_table, summary
from .scoring import analyse, repo_score
from .source import Source


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Command-line options."""
    parser = argparse.ArgumentParser(prog="code-health", description=__doc__)
    parser.add_argument("files", nargs="*", help="only report and gate these files (pre-commit passes them)")
    parser.add_argument(
        "--changed",
        nargs="?",
        const="",
        metavar="BASE",
        help="only files changed since BASE (default: origin/main, else main), uncommitted ones included",
    )
    parser.add_argument("--base", help="revision the given files must not get worse than (default: HEAD)")
    parser.add_argument("--json", action="store_true", help="machine-readable output for agents")
    parser.add_argument("--all", action="store_true", help="list files without smells too")
    parser.add_argument("--update-baseline", action="store_true", help="record the current scores (ratchet)")
    parser.add_argument("--exit-zero", action="store_true", help="report only, never fail")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: cwd)")
    return parser.parse_args(argv)


def collect(config: Config) -> list[str]:
    """Included Python files, relative to the root, minus the excluded ones."""
    paths: set[str] = set()
    for entry in config.include:
        target = config.root / entry
        found = [target] if target.is_file() else target.rglob("*.py")
        paths.update(path.relative_to(config.root).as_posix() for path in found)
    return sorted(path for path in paths if not any(fnmatch(path, pattern) for pattern in config.exclude))


def load_sources(texts: dict[str, str]) -> list[Source]:
    """Parse files, skipping (and reporting) the ones with syntax errors."""
    sources = []
    for path, text in texts.items():
        try:
            sources.append(Source.parse(path, text))
        except SyntaxError as error:
            print(f"code-health: skipping {path}: {error}", file=sys.stderr)
    return sources


@dataclass
class Selection:
    """The files to report (None: all) and the revision they must not get worse than."""

    paths: list[str] | None = None
    revision: str | None = None

    @classmethod
    def from_args(cls, args: argparse.Namespace, root: Path, known: list[str]) -> Selection:
        """``--changed`` (against the merge base), explicit files (against ``--base``) or all."""
        if args.changed is not None:
            merge_base, changed = changed_paths(root, args.changed or default_base(root))
            return cls(_known(changed, known), merge_base)
        if args.files:
            return cls(_known([Path(path).as_posix() for path in args.files], known), args.base or "HEAD")
        return cls()

    def keep(self, reports: list[FileReport]) -> list[FileReport]:
        """The selected reports."""
        return reports if self.paths is None else [report for report in reports if report.path in self.paths]


def _known(paths: list[str], known: list[str]) -> list[str]:
    """Included files among ``paths``; a directory stands for the files below it."""
    prefixes = tuple(f"{path.rstrip('/')}/" for path in paths)
    return [path for path in known if path in paths or path.startswith(prefixes)]


def previous_scores(config: Config, texts: dict[str, str], selection: Selection) -> dict[str, float]:
    """Scores of the selected files at the selection's revision, judged against today's other files."""
    if selection.revision is None or not selection.paths:
        return {}
    old = dict(texts)
    for path in selection.paths:
        before = text_at(config.root, selection.revision, path)
        if before is None:
            old.pop(path, None)
        else:
            old[path] = before
    return {report.path: report.score for report in selection.keep(analyse(load_sources(old), config))}


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the exit code (1 when the gate fails)."""
    args = parse_args(argv)
    config = config_module.load(args.root.resolve())
    known = collect(config)
    texts = {path: (config.root / path).read_text(encoding="utf-8") for path in known}
    reports = analyse(load_sources(texts), config)
    repo = repo_score(reports)
    selection = Selection.from_args(args, config.root, known)
    baseline = Baseline.load(config.baseline)
    gate = Gate(config.min_file_score, baseline, previous_scores(config, texts, selection))
    shown = selection.keep(reports)
    result = gate.check(shown, repo)
    totals = summary(reports, repo)
    print(
        as_json(shown, totals, result, config.version)
        if args.json
        else as_table(shown, totals, result, args.all)
    )
    if args.update_baseline:
        return _update_baseline(result.passed or baseline.version != config.version, reports, repo, config)
    return 0 if result.passed or args.exit_zero else 1


def _update_baseline(allowed: bool, reports: list[FileReport], repo: float, config: Config) -> int:
    """Ratchet: only when the gate passed, or to start over (no baseline yet, or a new config version)."""
    if not allowed:
        print(
            "code-health: not updating the baseline, the gate failed (it may only ratchet up)",
            file=sys.stderr,
        )
        return 1
    updated_baseline(reports, repo, config).save(config.baseline, config.version)
    print(f"code-health: baseline written to {config.baseline.name}", file=sys.stderr)
    return 0
