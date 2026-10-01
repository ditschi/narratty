"""Synthesizing a whole spec through the cache."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from narratty.cache import AudioCache
from narratty.errors import MissingDependencyError
from narratty.spec.loader import parse_spec
from narratty.tts.base import VoiceInfo
from narratty.tts.lexicon import Entry, Lexicon
from narratty.tts.synth import synthesize_spec
from tests.helpers import write_tone

SPEC = """\
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "cd demo"}, enter]
  - id: intro
    narration: Hello   there.
  - id: quiet
    actions: [{hold: 500}]
  - id: outro
    narration: Goodbye, and thanks for watching.
"""


class ToneProvider:
    """A provider whose 'speech' is a tone lasting 100 ms per word."""

    name = "tone"

    def __init__(self, *, available: bool = True, installed: bool = True) -> None:
        self.available = available
        self.installed = installed
        self.spoken: list[str] = []
        self.installs: list[str] = []

    def unavailable_reason(self) -> str | None:
        return None if self.available else "tone engine missing"

    def voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(self.name, "af_heart", "tone", "en", self.installed)]

    def is_installed(self, voice: str) -> bool:
        return self.installed

    def install(self, voice: str, *, show_progress: bool = True) -> None:
        self.installs.append(voice)
        self.installed = True

    def model_version(self, voice: str) -> str:
        return "tone 1"

    def synthesize(self, text: str, voice: str, out: Path, options: Mapping[str, Any]) -> None:
        self.spoken.append(text)
        write_tone(out, 100 * len(text.split()))


def test_one_clip_per_narrated_scene(tmp_path: Path) -> None:
    provider = ToneProvider()
    clips = synthesize_spec(parse_spec(SPEC, Path("t.narratty.yaml")), provider, AudioCache(tmp_path))
    assert [(c.scene_id, c.duration_ms, c.cached) for c in clips] == [
        ("intro", 200, False),
        ("outro", 500, False),
    ]
    assert provider.spoken == ["Hello there.", "Goodbye, and thanks for watching."]


def test_second_run_is_served_from_cache(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    synthesize_spec(parse_spec(SPEC, Path("t.narratty.yaml")), ToneProvider(), cache)
    provider = ToneProvider()
    seen: list[str] = []
    clips = synthesize_spec(
        parse_spec(SPEC, Path("t.narratty.yaml")), provider, cache, on_clip=lambda c: seen.append(c.scene_id)
    )
    assert all(c.cached for c in clips)
    assert provider.spoken == []
    assert seen == ["intro", "outro"]


def test_changed_narration_only_resynthesizes_that_scene(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    synthesize_spec(parse_spec(SPEC, Path("t.narratty.yaml")), ToneProvider(), cache)
    provider = ToneProvider()
    changed = SPEC.replace("Goodbye, and", "Bye and")
    clips = synthesize_spec(parse_spec(changed, Path("t.narratty.yaml")), provider, cache)
    assert [c.cached for c in clips] == [True, False]
    assert provider.spoken == ["Bye and thanks for watching."]


def test_missing_voice_is_downloaded(tmp_path: Path) -> None:
    provider = ToneProvider(installed=False)
    synthesize_spec(
        parse_spec(SPEC, Path("t.narratty.yaml")), provider, AudioCache(tmp_path), show_progress=False
    )
    assert provider.installs == ["af_heart"]


def test_offline_fails_before_synthesizing(tmp_path: Path) -> None:
    provider = ToneProvider(installed=False)
    with pytest.raises(MissingDependencyError, match="not installed") as raised:
        synthesize_spec(
            parse_spec(SPEC, Path("t.narratty.yaml")), provider, AudioCache(tmp_path), download=False
        )
    assert "voices pull af_heart" in (raised.value.hint or "")
    assert provider.spoken == []


def test_unavailable_engine_fails_early(tmp_path: Path) -> None:
    with pytest.raises(MissingDependencyError, match="tone engine missing"):
        synthesize_spec(
            parse_spec(SPEC, Path("t.narratty.yaml")), ToneProvider(available=False), AudioCache(tmp_path)
        )


def test_lexicon_changes_only_what_is_spoken(tmp_path: Path) -> None:
    spec = parse_spec(SPEC.replace("Hello   there.", "Edit .bazelrc there."), Path("t.narratty.yaml"))
    provider = ToneProvider()
    lexicon = Lexicon([Entry(".bazelrc", "dot bay zel R C", "spec")])
    synthesize_spec(spec, provider, AudioCache(tmp_path), lexicon=lexicon)
    assert provider.spoken[0] == "Edit dot bay zel R C there."
    assert spec.scenes[1].narration == "Edit .bazelrc there."
    again = ToneProvider()
    clips = synthesize_spec(
        spec, again, AudioCache(tmp_path), lexicon=Lexicon([Entry(".bazelrc", "dot bazel", "spec")])
    )
    assert [c.cached for c in clips] == [False, True], "a changed respelling re-synthesizes that clip"
