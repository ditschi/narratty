"""Integration tests run real engines.

Voices are kept in the normal data directory (or ``NARRATTY_DATA_DIR``) so CI can
cache them between runs; the audio cache is per test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _fresh_audio_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATTY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NARRATTY_RUNTIME", "native")
    monkeypatch.setenv("NARRATTY_CONFIG_DIR", str(tmp_path / "config"))
