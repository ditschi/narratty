"""Spec model rules."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from narratty.spec.model import CtrlSequence, Enter, Hold, Key, Run, Sandbox, Spec, TypeCommand, Wait


def _spec(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"scenes": [{"id": "intro", "narration": "Hello.", "actions": ["enter"]}]}
    data.update(overrides)
    return data


def test_defaults() -> None:
    spec = Spec.model_validate(_spec())
    assert (spec.tts.provider, spec.tts.voice) == ("kokoro", "af_heart")
    assert spec.timing.narration_buffer_ms == 500
    assert spec.workspace.mode == "snapshot"
    assert spec.sandbox.network == "none"
    assert not spec.sandbox.elevated


def test_default_voice_follows_the_provider() -> None:
    assert Spec.model_validate(_spec(tts={"provider": "piper"})).tts.voice == "en_US-lessac-medium"
    assert Spec.model_validate(_spec(tts={"provider": "kokoro"})).tts.voice == "af_heart"
    assert Spec.model_validate(_spec(tts={"voice": "bf_emma"})).tts.voice == "bf_emma"


def test_all_action_forms_parse() -> None:
    actions = [
        {"type_command": "ls"},
        "enter",
        {"enter": True},
        {"ctrl_sequence": "C-c"},
        {"hold": 250},
        {"wait": {"screen": r"\$ $"}},
        {"key": "Down 3"},
        {"hold": "auto"},
        {"run": "make"},
        {"wait": "done"},
    ]
    spec = Spec.model_validate(_spec(scenes=[{"id": "a", "narration": "x", "actions": actions}]))
    kinds = [type(a) for a in spec.scenes[0].actions]
    assert kinds == [TypeCommand, Enter, Enter, CtrlSequence, Hold, Wait, Key, Hold, Run, Wait]


def test_wait_shorthand_uses_the_default_timeout() -> None:
    spec = Spec.model_validate(_spec(scenes=[{"id": "a", "actions": [{"wait": "done"}]}]))
    wait = spec.scenes[0].actions[0]
    assert isinstance(wait, Wait)
    assert (wait.wait.screen, wait.wait.timeout_ms) == ("done", 15000)


def test_narration_whitespace_is_collapsed() -> None:
    spec = Spec.model_validate(_spec(scenes=[{"id": "a", "narration": "  one\n two  \n"}]))
    assert spec.scenes[0].narration == "one two"


@pytest.mark.parametrize(
    ("scene", "message"),
    [
        ({"id": "a", "hidden": True, "narration": "x"}, "hidden scene cannot have narration"),
        ({"id": "a", "actions": [{"hold": "auto"}]}, "needs narration"),
        ({"id": "a", "narration": "x", "actions": [{"hold": "auto"}, {"hold": "auto"}]}, "only one"),
        ({"id": "Bad Id"}, "String should match pattern"),
        ({"id": "a", "actions": [{"hold": 0}]}, "positive duration"),
        ({"id": "a", "actions": [{"key": "F13"}]}, "unknown key"),
        ({"id": "a", "actions": [{"ctrl_sequence": "C-cc"}]}, "String should match pattern"),
        ({"id": "a", "actions": [{"wait": {"screen": "("}}]}, "regular expression"),
        ({"id": "a", "actions": [{"type_command": "ls", "enter": True}]}, "exactly one"),
        ({"id": "a", "actions": [{"run": ""}]}, "at least 1 character"),
        ({"id": "a", "actions": [{"wait": "("}]}, "regular expression"),
    ],
)
def test_invalid_scenes(scene: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Spec.model_validate(_spec(scenes=[scene]))


def test_duplicate_scene_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate scene id 'a'"):
        Spec.model_validate(_spec(scenes=[{"id": "a"}, {"id": "a"}]))


def test_needs_at_least_one_scene() -> None:
    with pytest.raises(ValidationError):
        Spec.model_validate({"scenes": []})


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        Spec.model_validate(_spec(terminal={"widht": 10}))


def test_allowlist_rules() -> None:
    with pytest.raises(ValidationError, match="only applies"):
        Sandbox.model_validate({"allow_hosts": ["a.example:1"]})
    with pytest.raises(ValidationError, match="at least one"):
        Sandbox.model_validate({"network": "allowlist"})
    sandbox = Sandbox.model_validate({"network": "allowlist", "allow_hosts": ["lic.example:27000"]})
    assert sandbox.elevated


def test_provider_options() -> None:
    spec = Spec.model_validate(
        _spec(tts={"provider": "kokoro", "voice": "af_heart", "kokoro": {"speed": 1.2}})
    )
    assert spec.tts.provider_options() == {"speed": 1.2, "lang": None}
    assert Spec.model_validate(_spec(tts={"provider": "custom"})).tts.provider_options() == {}


@pytest.mark.parametrize(("value", "enabled"), [(False, False), (True, True), ({}, None)])
def test_end_card_shorthand(value: Any, enabled: bool | None) -> None:
    spec = Spec.model_validate(_spec(end_card=value))
    assert spec.end_card.enabled is enabled
    assert spec.end_card.duration_ms == 4000 and spec.end_card.qr


def test_end_card_needs_a_visible_duration() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1000"):
        Spec.model_validate(_spec(end_card={"duration_ms": 200}))


def test_key_names_are_case_insensitive() -> None:
    actions = [{"key": "enter"}, {"key": "down 3"}, {"key": "PageUp"}]
    spec = Spec.model_validate(_spec(scenes=[{"id": "a", "actions": actions}]))
    assert [a.key for a in spec.scenes[0].actions if isinstance(a, Key)] == ["Enter", "Down 3", "PageUp"]


@pytest.mark.parametrize(
    ("value", "ms"), [(250, 250), ("250ms", 250), ("1.5s", 1500), ("2m", 120000), (" 2s ", 2000)]
)
def test_durations(value: Any, ms: int) -> None:
    spec = Spec.model_validate(
        _spec(
            timing={"tail_ms": value},
            scenes=[
                {"id": "a", "actions": [{"hold": value}, {"wait": {"screen": "x", "timeout_ms": value}}]}
            ],
        )
    )
    hold, wait = spec.scenes[0].actions
    assert isinstance(hold, Hold) and isinstance(wait, Wait)
    assert (spec.timing.tail_ms, hold.hold, wait.wait.timeout_ms) == (ms, ms, ms)


@pytest.mark.parametrize("value", ["1.5", "1.5 h", "fast", "-1s", "0s"])
def test_invalid_durations(value: str) -> None:
    with pytest.raises(ValidationError):
        Spec.model_validate(_spec(scenes=[{"id": "a", "actions": [{"hold": value}]}]))
