"""The gate and the command line of tools/code_health, in a scratch git repository."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.code_health.cli import main
from tools.code_health.gate import Baseline, Gate
from tools.code_health.model import FileReport

ROOT = Path(__file__).resolve().parents[3]
CLEAN = "def f(x):\n    return x + 1\n"
BRANCHY = (
    "def f(x):\n" + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(14)) + "    return -1\n"
)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    shutil.copy(ROOT / "code-health.toml", tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text(CLEAN)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "files")
    return tmp_path


def run(repo: Path, *args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = main(["--root", str(repo), "--json", *args])
    return code, json.loads(capsys.readouterr().out)


def test_gate_flags_low_and_dropping_scores() -> None:
    gate = Gate(9.5, Baseline(files={"old.py": 8.0}), previous={"new.py": 10.0})
    result = gate.check([FileReport("old.py", 10, 8.0), FileReport("new.py", 10, 9.6)], repo=9.9)
    assert result.violations == ["new.py: score dropped from 10.00 to 9.60"]


def test_gate_holds_the_repo_score_to_the_baseline() -> None:
    result = Gate(9.5, Baseline(repo_score=9.8)).check([], repo=9.7)
    assert not result.passed


def test_clean_repository_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run(repo, capsys=capsys)
    assert (code, data["repo_score"], data["gate"]["passed"]) == (0, 10.0, True)


def test_changed_reports_only_changed_files_and_fails_below_minimum(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "src" / "new.py").write_text(BRANCHY)
    code, data = run(repo, "--changed", "main", capsys=capsys)
    assert code == 1
    assert [report["path"] for report in data["reports"]] == ["src/new.py"]


def test_baseline_lets_known_files_stay_but_not_get_worse(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "src" / "ok.py").write_text(BRANCHY)
    baseline = repo / "code-health-baseline.json"
    baseline.write_text(json.dumps({"version": 1, "files": {}}))
    assert main(["--root", str(repo), "--update-baseline", "--exit-zero"]) == 1  # gate fails: no ratchet down
    baseline.write_text(json.dumps({"version": 1, "files": {"src/ok.py": 8.0}}))
    capsys.readouterr()
    code, data = run(repo, "src/ok.py", "--base", "HEAD", capsys=capsys)
    assert code == 1
    assert data["gate"]["violations"] == [
        f"src/ok.py: score dropped from 10.00 to {data['reports'][0]['score']:.2f}"
    ]


def test_update_baseline_records_files_below_the_minimum(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "src" / "ok.py").write_text(BRANCHY)
    (repo / "code-health-baseline.json").write_text(json.dumps({"files": {"src/ok.py": 1.0}}))
    assert main(["--root", str(repo), "--update-baseline"]) == 0
    recorded = json.loads((repo / "code-health-baseline.json").read_text())
    assert list(recorded["files"]) == ["src/ok.py"]
