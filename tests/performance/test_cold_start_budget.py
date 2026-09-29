"""CLI cold-start latency budgets, so help and shell completion stay snappy."""

from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import time

import pytest

pytestmark = pytest.mark.performance

SAMPLES = 5
# Conservative budgets for shared CI runners.
HELP_BUDGET_S = 1.0
COMPLETION_BUDGET_S = 1.0


def _median(args: list[str], extra_env: dict[str, str] | None = None) -> float:
    exe = shutil.which("narratty")
    if exe is None:
        pytest.fail("narratty console script not on PATH; install the package first (nox -s performance).")
    env = {**os.environ, **(extra_env or {})}
    elapsed = []
    for _ in range(SAMPLES):
        start = time.perf_counter()
        subprocess.run([exe, *args], check=False, capture_output=True, env=env)
        elapsed.append(time.perf_counter() - start)
    return statistics.median(elapsed)


def test_help_budget() -> None:
    assert _median(["--help"]) < HELP_BUDGET_S


def test_completion_budget() -> None:
    env = {
        "_NARRATTY_COMPLETE": "complete_bash",
        "COMP_WORDS": "narratty doctor --runtime ",
        "COMP_CWORD": "3",
    }
    assert _median([], env) < COMPLETION_BUDGET_S
