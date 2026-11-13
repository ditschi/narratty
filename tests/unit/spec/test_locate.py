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


def test_hints_for_markdown_docs_use_markdown_terms(doc: Path, tmp_path: Path) -> None:
    from narratty.errors import CommandError
    from narratty.render.cast import wait_timeout
    from narratty.render.exits import check

    log = tmp_path / "exits.log"
    log.write_text("1\tprintf x\n", encoding="utf-8")
    from narratty.spec.loader import load_spec

    with pytest.raises(CommandError) as raised, located(doc):
        check(load_spec(doc), log)
    assert raised.value.hint is not None
    assert 'narratty="expect-failure"' in raised.value.hint
    assert "expect_exit: failure" not in raised.value.hint
    with pytest.raises(RenderError) as timed_out, located(doc):
        raise wait_timeout(1000, "ready", None)
    assert timed_out.value.hint is not None
    assert "`timeout` in the block's run comment" in timed_out.value.hint
    assert "wait.timeout_ms" not in timed_out.value.hint
