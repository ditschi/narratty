"""Keep unit tests away from the real data and cache directories."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATTY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NARRATTY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NARRATTY_RUNTIME", "native")
    monkeypatch.setenv("NARRATTY_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("NARRATTY_IN_CONTAINER", raising=False)
    monkeypatch.delenv("NARRATTY_WORKSPACE", raising=False)
    monkeypatch.delenv("NARRATTY_BRIDGE", raising=False)
    monkeypatch.delenv("NARRATTY_AGENT_DIR", raising=False)
    monkeypatch.delenv("NARRATTY_TOOLKIT_IMAGE", raising=False)


@pytest.fixture(autouse=True)
def _rootful_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Container user flags as with a rootful daemon, whatever this machine runs."""
    monkeypatch.setattr("narratty.runtime.docker_is_rootless", lambda: False)


@pytest.fixture(autouse=True)
def _images_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never pull container images; ``test_container`` tests ``ensure_image`` itself."""
    monkeypatch.setattr("narratty.container.ensure_image", lambda engine, image: None)
    monkeypatch.setattr("narratty.container.warn_image_version", lambda engine, image: None)
