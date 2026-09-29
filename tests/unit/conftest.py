"""Keep unit tests away from the real data and cache directories."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATTY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NARRATTY_CACHE_DIR", str(tmp_path / "cache"))
