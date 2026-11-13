"""Errors in a scene name the Markdown line it came from."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from narratty.errors import RenderError
from narratty.spec.compile import SCENE_SOURCES_ENV, located, scene_sources


@pytest.fixture
def doc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "guide.md"
    path.write_text("# Guide\n\nRun it:\n\n```console\n$ printf x\n```\n", encoding="utf-8")
    return path


def test_scene_sources_are_markdown_lines(doc: Path) -> None:
    sources = scene_sources(doc)
    assert sources and all(value.startswith("guide.md:") for value in sources.values())


def test_located_adds_the_source_to_the_scene(doc: Path) -> None:
    scene, source = next(iter(scene_sources(doc).items()))
    with pytest.raises(RenderError) as raised, located(doc):
        raise RenderError(f"timed out in scene {scene!r} waiting", scene=scene)
    assert raised.value.message == f"timed out in scene {scene!r} ({source}) waiting"
    with pytest.raises(RenderError) as raised, located(doc):
        raise RenderError("VHS failed", scene=scene)
    assert raised.value.message == f"VHS failed (scene {scene!r}, {source})"
    with pytest.raises(RenderError) as raised, located(doc):
        raise RenderError("no scene")
    assert raised.value.message == "no scene"


def test_a_container_gets_the_sources_from_the_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = tmp_path / "compiled.narratty.yaml"
    spec.write_text("scenes:\n  - id: a\n    actions: [enter]\n", encoding="utf-8")
    monkeypatch.setitem(os.environ, SCENE_SOURCES_ENV, json.dumps({"a": "docs/guide.md:7"}))
    with pytest.raises(RenderError) as raised, located(spec):
        raise RenderError("boom", scene="a")
    assert raised.value.message == "boom (scene 'a', docs/guide.md:7)"
