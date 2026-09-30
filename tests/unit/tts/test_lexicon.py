"""Pronunciation lexicon: matching, layering and the container hand-over."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest

from narratty.errors import UsageError
from narratty.spec.model import TtsConfig
from narratty.tts.lexicon import (
    ENV_OVERRIDE,
    Entry,
    Lexicon,
    export_host_entries,
    load_lexicon,
    parse_entries,
    project_file,
    to_toml,
    voice_language,
)


def _lexicon(**pairs: str) -> Lexicon:
    return Lexicon(parse_entries(pairs, "test"))


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("Edit .bazelrc now.", "Edit dot bay zel R C now."),
        ("All .bazel files", "All dot bay zel files"),
        ("See .gitignore ... done.Next 3.14", "See dot gitignore ... done.Next 3.14"),
        ("Run bazel. Bazel builds.", "Run bay zel. bay zel builds."),
        ("Keep file.bazel and bazelisk", "Keep file.bazel and bazelisk"),
        ("Call bm_rat_b twice", "Call B M rat B twice"),
    ],
)
def test_whole_words_and_leading_dots(text: str, spoken: str) -> None:
    lexicon = _lexicon(**{".bazelrc": "dot bay zel R C", "bazel": "bay zel", "bm_rat_b": "B M rat B"})
    assert lexicon.apply(text) == spoken


def test_capitalised_terms_match_only_their_case() -> None:
    lexicon = _lexicon(API="A P I", nix="nicks")
    assert lexicon.apply("API api NIX") == "A P I api nicks"


def test_later_entries_win() -> None:
    lexicon = Lexicon(
        [
            Entry("kubectl", "cube control", "a"),
            Entry("Kubectl", "x", "b"),
            Entry("kubectl", "cube C T L", "c"),
        ]
    )
    assert lexicon.apply("kubectl") == "cube C T L"
    assert [e.source for e in lexicon.entries] == ["b", "c"]


def test_table_form_and_invalid_entries() -> None:
    assert parse_entries({"nginx": {"say": "engine x"}}, "f") == [Entry("nginx", "engine x", "f")]
    for bad in ({"x": ""}, {"x": 1}, {"x": {"ipa": "..."}}, {" ": "y"}):
        with pytest.raises(UsageError, match="invalid lexicon entry"):
            parse_entries(bad, "f")


def test_unknown_words() -> None:
    lexicon = _lexicon(bazel="bay zel")
    text = "Run .bazel, .my_rc, k8s and myTool and YAML on file.py; skip the API. Plain words pass, API too."
    assert lexicon.unknown_words(text) == [".my_rc", "k8s", "myTool", "YAML", "file.py", "API"]


@pytest.mark.parametrize(
    ("tts", "language"),
    [
        (TtsConfig(), "en-us"),
        (TtsConfig(voice="ff_siwis"), "fr-fr"),
        (TtsConfig.model_validate({"provider": "piper", "voice": "de_DE-thorsten-medium"}), "de_DE"),
    ],
)
def test_voice_language(tts: TtsConfig, language: str) -> None:
    assert voice_language(tts) == language


def _spec_in_repo(tmp_path: Path) -> Path:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    spec = tmp_path / "repo" / "docs" / "demo.narratty.yaml"
    spec.parent.mkdir()
    spec.write_text("scenes: [{id: a}]\n", encoding="utf-8")
    return spec


def test_levels_merge_in_order(tmp_path: Path) -> None:
    spec = _spec_in_repo(tmp_path)
    config = Path(os.environ["NARRATTY_CONFIG_DIR"])
    config.mkdir()
    (config / "lexicon.toml").write_text('kubectl = "kube C T L"\nbazel = "user"\n', encoding="utf-8")
    (tmp_path / "repo" / "narratty.lexicon.toml").write_text(
        'bazel = "project"\nnix = "nicks"\n', encoding="utf-8"
    )
    lexicon = load_lexicon(spec, TtsConfig(lexicon={"nix": "spec"}))
    assert lexicon.apply("kubectl bazel nix stdout") == "kube C T L project spec standard out"
    sources = {e.term: e.source for e in lexicon.entries}
    assert sources["stdout"] == "built-in"
    assert sources["nix"] == "spec"


def test_builtin_only_for_english_voices(tmp_path: Path) -> None:
    spec = _spec_in_repo(tmp_path)
    german = TtsConfig.model_validate(
        {"provider": "piper", "voice": "de_DE-thorsten-medium", "lexicon": {"nix": "nicks"}}
    )
    assert [e.term for e in load_lexicon(spec, german).entries] == ["nix"]


def test_project_file_search_stops_at_repo_root(tmp_path: Path) -> None:
    spec = _spec_in_repo(tmp_path)
    (tmp_path / "narratty.lexicon.toml").write_text('x = "y"\n', encoding="utf-8")
    assert project_file(spec) is None
    nearest = spec.parent / "narratty.lexicon.toml"
    nearest.write_text('x = "z"\n', encoding="utf-8")
    assert project_file(spec) == nearest


def test_container_gets_the_host_levels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec_in_repo(tmp_path)
    (tmp_path / "repo" / "narratty.lexicon.toml").write_text('"a\\"b" = "é"\n', encoding="utf-8")
    exported = export_host_entries(spec, tmp_path / "out")
    assert tomllib.loads(exported.read_text(encoding="utf-8")) == {'a"b': "é"}
    (tmp_path / "repo" / "narratty.lexicon.toml").unlink()
    monkeypatch.setenv(ENV_OVERRIDE, str(exported))
    assert load_lexicon(spec, TtsConfig()).say('a"b') == "é"


def test_to_toml_round_trips() -> None:
    entries = [Entry(".bazelrc", "dot bay zel R C", "x"), Entry("C++", "C plus plus", "x")]
    assert tomllib.loads(to_toml(entries)) == {".bazelrc": "dot bay zel R C", "C++": "C plus plus"}
