"""The gate: changed files reach the minimum and get no worse; the repo score never drops.

While files sit below the minimum, the ratchet baseline (``code-health-baseline.json``)
records their scores and the repository score; they may stay below the minimum as long
as they do not fall under their recorded score.
"""
# aihealth: disable=primitive_obsession -- temporary cross-check for aihealth, removed afterwards

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .model import FileReport


@dataclass
class Baseline:
    """Recorded scores the ratchet compares against."""

    repo_score: float | None = None
    files: dict[str, float] = field(default_factory=dict)
    version: int | None = None

    @classmethod
    def load(cls, path: Path) -> Baseline:
        """Read the baseline; an absent file means no exceptions."""
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("repo_score"), dict(data.get("files", {})), data.get("version"))

    def save(self, path: Path, version: int) -> None:
        """Write the baseline (sorted, so diffs stay small)."""
        data = {"version": version, "repo_score": self.repo_score, "files": dict(sorted(self.files.items()))}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@dataclass
class GateResult:
    """Violations found by the gate; empty means it passed."""

    violations: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Whether nothing failed."""
        return not self.violations


@dataclass
class Gate:
    """What the reported files are held to."""

    min_file_score: float
    baseline: Baseline
    # Scores at the base revision (``--changed`` and pre-commit); files must not drop below.
    previous: dict[str, float] = field(default_factory=dict)

    def check(self, reports: list[FileReport], repo: float) -> GateResult:
        """Violations of ``reports`` and of the repository score ``repo``."""
        result = GateResult()
        for report in reports:
            result.violations += self._file_violations(report)
        recorded = self.baseline.repo_score
        if recorded is not None and repo < recorded:
            result.violations.append(f"repository score {repo:.2f} dropped below the baseline {recorded:.2f}")
        return result

    def _file_violations(self, report: FileReport) -> list[str]:
        violations = []
        allowed = self.baseline.files.get(report.path)
        floor_score = self.min_file_score if allowed is None else min(allowed, self.min_file_score)
        if report.score < floor_score:
            floor = f"its baseline {allowed:.2f}" if allowed is not None else f"{self.min_file_score:.2f}"
            violations.append(f"{report.path}: score {report.score:.2f} is below {floor}")
        before = self.previous.get(report.path)
        if before is not None and report.score < before:
            violations.append(f"{report.path}: score dropped from {before:.2f} to {report.score:.2f}")
        return violations


def updated_baseline(reports: list[FileReport], repo: float, config: Config) -> Baseline:
    """The baseline for the current state: every file below the minimum, plus the repo score."""
    below = {report.path: report.score for report in reports if report.score < config.min_file_score}
    return Baseline(repo_score=repo, files=below)


def git(root: Path, *args: str) -> str:
    """Run git in ``root`` and return its stdout."""
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def default_base(root: Path) -> str:
    """``origin/main`` when it exists, otherwise ``main``."""
    try:
        git(root, "rev-parse", "--verify", "--quiet", "origin/main")
    except subprocess.CalledProcessError:
        return "main"
    return "origin/main"


def changed_paths(root: Path, base: str) -> tuple[str, list[str]]:
    """The merge base with ``base`` and the files changed since then, uncommitted ones included."""
    merge_base = git(root, "merge-base", base, "HEAD").strip()
    changed = git(root, "diff", "--name-only", "--diff-filter=ACMR", merge_base).splitlines()
    untracked = git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return merge_base, sorted(set(changed) | set(untracked))


def text_at(root: Path, revision: str, path: str) -> str | None:
    """The file's content at ``revision``, or None if it did not exist there."""
    try:
        return git(root, "show", f"{revision}:{path}")
    except subprocess.CalledProcessError:
        return None
