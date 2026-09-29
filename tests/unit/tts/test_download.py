"""Checksummed, atomic downloads."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from narratty.errors import MissingDependencyError
from narratty.tts.catalog import RemoteFile
from narratty.tts.download import download


def _source(tmp_path: Path, content: bytes = b"model bytes") -> Path:
    path = tmp_path / "upstream.bin"
    path.write_bytes(content)
    return path


def test_downloads_and_verifies(tmp_path: Path) -> None:
    source = _source(tmp_path)
    digest = hashlib.sha256(b"model bytes").hexdigest()
    target = download(RemoteFile("m.bin", source.as_uri(), digest), tmp_path / "dest", show_progress=False)
    assert target.read_bytes() == b"model bytes"
    assert not list((tmp_path / "dest").glob("*.part"))


def test_checksum_mismatch_leaves_nothing_behind(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(MissingDependencyError, match="checksum mismatch"):
        download(RemoteFile("m.bin", source.as_uri(), "0" * 64), tmp_path / "dest", show_progress=False)
    assert list((tmp_path / "dest").iterdir()) == []


def test_unreachable_url_is_a_missing_dependency(tmp_path: Path) -> None:
    missing = (tmp_path / "nope.bin").as_uri()
    with pytest.raises(MissingDependencyError, match="could not download"):
        download(RemoteFile("m.bin", missing), tmp_path / "dest", show_progress=False)
    assert list((tmp_path / "dest").iterdir()) == []
