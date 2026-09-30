"""Pronunciation lexicon: say a term differently from how the narration spells it.

Narration keeps the real spelling (``.bazelrc``, ``kubectl``), which stays searchable
and readable; the lexicon swaps in a respelling right before synthesis. Four levels
are merged, later wins:

1. built-in (``narratty/data/lexicon.toml``), only for English voices
2. user: ``lexicon.toml`` in the config directory
3. project: the nearest ``narratty.lexicon.toml`` from the spec up to the repo root
4. spec: ``tts.lexicon``

Matching is whole-word. A term with a capital letter matches only that exact case;
an all-lowercase term matches any case. A leading dot is spoken as "dot" (``.gitignore``
→ "dot gitignore"), also before a matched term.
"""

from __future__ import annotations

import hashlib
import os
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from narratty.errors import UsageError
from narratty.spec.model import TtsConfig

PROJECT_FILE = "narratty.lexicon.toml"
USER_FILE = "lexicon.toml"
# Set inside the container: one file with the host's merged user and project levels.
ENV_OVERRIDE = "NARRATTY_LEXICON"

DOT = "dot"
_LEADING_DOT = re.compile(r"(?<![\w.])\.(?=[A-Za-z])")

# Words a TTS engine likely mangles: dotted, with underscores, digits, camelCase or all-caps.
_SUSPICIOUS = re.compile(
    r"(?<![\w.])(?:"
    r"\.?[A-Za-z][\w-]*[._][\w.-]*\w"  # .bazelrc, bm_rat_b, file.py
    r"|\.[A-Za-z]\w+"  # .bazel
    r"|[A-Za-z]+\d[\w]*"  # k8s, py312
    r"|[a-z]+[A-Z]\w*"  # camelCase
    r"|[A-Z]{2,}[a-z]?s?"  # YAML, CLIs
    r")(?!\w)"
)


@dataclass(frozen=True)
class Entry:
    """One term and how to say it."""

    term: str
    say: str
    source: str


def _is_case_sensitive(term: str) -> bool:
    return term != term.lower()


class Lexicon:
    """Merged entries; :meth:`apply` rewrites narration for the TTS engine."""

    def __init__(self, entries: Iterable[Entry] = ()) -> None:
        merged: dict[str, Entry] = {}
        for entry in entries:
            key = entry.term if _is_case_sensitive(entry.term) else entry.term.lower()
            merged.pop(key, None)  # keep insertion order = order of the winning level
            merged[key] = entry
        self.entries = list(merged.values())
        self._exact = {e.term: e.say for e in self.entries if _is_case_sensitive(e.term)}
        self._folded = {e.term: e.say for e in self.entries if not _is_case_sensitive(e.term)}
        terms = sorted({e.term for e in self.entries}, key=len, reverse=True)
        self._pattern = (
            re.compile(
                r"(?<![\w.])\.?(?:" + "|".join(re.escape(t) for t in terms) + r")(?!\w)", re.IGNORECASE
            )
            if terms
            else None
        )

    def __bool__(self) -> bool:
        return bool(self.entries)

    def say(self, word: str) -> str | None:
        """The replacement for ``word``, or None when no entry matches it."""
        if word in self._exact:
            return self._exact[word]
        if (spoken := self._folded.get(word.lower())) is not None:
            return spoken
        if word.startswith(".") and (rest := self.say(word[1:])) is not None:
            return f"{DOT} {rest}"
        return None

    def apply(self, text: str) -> str:
        """``text`` with every matching term replaced by its spoken form.

        A leading dot left over (``.gitignore``) is spoken as "dot", which engines drop.
        """
        if self._pattern is not None:

            def replace(match: re.Match[str]) -> str:
                word = match.group(0)
                spoken = self.say(word)
                return word if spoken is None else spoken

            text = self._pattern.sub(replace, text)
        return _LEADING_DOT.sub(f"{DOT} ", text)

    def unknown_words(self, text: str) -> list[str]:
        """Words that look hard to pronounce and no entry covers, in order, without repeats."""
        found: list[str] = []
        for match in _SUSPICIOUS.finditer(text):
            word = match.group(0)
            if word.startswith(".") and not _SUSPICIOUS.fullmatch(word[1:]):
                continue  # ".bazel" is spoken as "dot bazel"
            if word not in found and self.say(word) is None:
                found.append(word)
        return found


def parse_entries(data: Mapping[str, Any], source: str) -> list[Entry]:
    """Entries from ``term = "say"`` or ``[term] say = "..."`` pairs."""
    entries: list[Entry] = []
    for term, value in data.items():
        say = value.get("say") if isinstance(value, dict) else value
        extra = set(value) - {"say"} if isinstance(value, dict) else set()
        if not term.strip() or not isinstance(say, str) or not say.strip() or extra:
            raise UsageError(
                f"{source}: invalid lexicon entry {term!r}",
                hint='Write `term = "how to say it"` or a [term] table with a `say` key.',
            )
        entries.append(Entry(term.strip(), say.strip(), source))
    return entries


def read_file(path: Path) -> list[Entry]:
    """Entries of one lexicon TOML file."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    return parse_entries(data, str(path))


@cache
def builtin_entries() -> tuple[Entry, ...]:
    """The lexicon shipped with narratty."""
    text = files("narratty").joinpath("data/lexicon.toml").read_text(encoding="utf-8")
    return tuple(parse_entries(tomllib.loads(text), "built-in"))


def project_file(spec_path: Path) -> Path | None:
    """The nearest ``narratty.lexicon.toml`` from the spec's directory up to the repo root."""
    directory = spec_path.resolve().parent
    for candidate in (directory, *directory.parents):
        path = candidate / PROJECT_FILE
        if path.is_file():
            return path
        if (candidate / ".git").exists():
            return None
    return None


def host_entries(spec_path: Path, config_directory: Path | None = None) -> list[Entry]:
    """User and project levels, which only exist on the host."""
    from narratty.config import config_dir

    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return read_file(Path(override))
    entries: list[Entry] = []
    user = (config_directory or config_dir()) / USER_FILE
    if user.is_file():
        entries += read_file(user)
    project = project_file(spec_path)
    if project is not None:
        entries += read_file(project)
    return entries


def voice_language(tts: TtsConfig) -> str:
    """Language of the spec's voice (``en-us``, ``de_DE``, …)."""
    from narratty.tts.catalog import kokoro_language

    if tts.provider == "kokoro":
        return tts.kokoro.lang or kokoro_language(tts.voice)
    return tts.voice.split("-", 1)[0]


def load_lexicon(spec_path: Path, tts: TtsConfig) -> Lexicon:
    """All four levels merged for the spec at ``spec_path``."""
    builtin = builtin_entries() if voice_language(tts).lower().startswith("en") else ()
    return Lexicon([*builtin, *host_entries(spec_path), *parse_entries(tts.lexicon, "spec")])


def to_toml(entries: Iterable[Entry]) -> str:
    """Entries as a lexicon TOML file (for handing the host levels to the container)."""
    import json

    # JSON strings are valid TOML basic strings for everything a term or respelling holds.
    return "".join(
        f"{json.dumps(e.term, ensure_ascii=False)} = {json.dumps(e.say, ensure_ascii=False)}\n"
        for e in entries
    )


def export_host_entries(spec_path: Path, directory: Path) -> Path:
    """Write the host levels to a content-addressed file in ``directory``."""
    text = to_toml(host_entries(spec_path))
    path = directory / f"{hashlib.sha256(text.encode()).hexdigest()[:16]}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
