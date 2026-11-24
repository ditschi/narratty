"""Compare aihealth component scores between the merge base and HEAD (CI gate).

`aihealth delta` judges the changed files; this also catches a component whose overall
score drops, e.g. because a large healthy file was replaced by a small unhealthy one.
Components missing at the merge base are reported but not compared.

    python tools/aihealth_components.py [BASE]     # default: origin/main, else main
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".aihealth.toml"
COMPONENTS = ("src/narratty", "tests", "agent", "tools", "docker", "examples")
AIHEALTH = ("uv", "run", "--quiet", "--locked", "--isolated", "--only-group", "code-health", "aihealth")


@dataclass(frozen=True)
class Comparison:
    """One component's score before and after (None: the component does not exist)."""

    component: str
    before: float | None
    after: float | None

    @property
    def dropped(self) -> bool:
        """Whether the component got worse (any drop: the tolerance is 0)."""
        if self.before is None or self.after is None:
            return False
        return self.after < self.before

    def line(self) -> str:
        """One table row."""
        before = "-" if self.before is None else f"{self.before:.2f}"
        after = "-" if self.after is None else f"{self.after:.2f}"
        mark = "  DROPPED" if self.dropped else ""
        return f"{self.component:<14} {before:>6} -> {after:>6}{mark}"


def score(tree: Path, component: str) -> float | None:
    """aihealth project score of ``component`` inside ``tree`` (None if it is absent)."""
    target = tree / component
    if not target.exists():
        return None
    command = [*AIHEALTH, "scan", str(target), "--config", str(CONFIG), "--format", "json"]
    output = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return float(json.loads(output)["score"])


def git(*args: str) -> str:
    """Run git in the repository and return its stdout."""
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def default_base() -> str:
    """``origin/main`` when it exists, otherwise ``main``."""
    try:
        git("rev-parse", "--verify", "--quiet", "origin/main")
    except subprocess.CalledProcessError:
        return "main"
    return "origin/main"


def compare(base: str) -> list[Comparison]:
    """Scores of every component at the merge base with ``base`` and in the working tree."""
    merge_base = git("merge-base", base, "HEAD")
    with tempfile.TemporaryDirectory() as scratch:
        before_tree = Path(scratch) / "base"
        git("worktree", "add", "--detach", str(before_tree), merge_base)
        try:
            return [Comparison(name, score(before_tree, name), score(ROOT, name)) for name in COMPONENTS]
        finally:
            git("worktree", "remove", "--force", str(before_tree))
            git("worktree", "prune")


def main(argv: list[str]) -> int:
    """Print the comparison; exit 1 when a component dropped, 2 when git or aihealth failed."""
    try:
        comparisons = compare(argv[0] if argv else default_base())
    except subprocess.CalledProcessError as error:
        print(f"{' '.join(error.cmd)} failed:\n{error.stderr}", file=sys.stderr)
        return 2
    print("component      before    after")
    print("\n".join(comparison.line() for comparison in comparisons))
    return 1 if any(comparison.dropped for comparison in comparisons) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
