"""Subtitles from the narration: one or more cues per clip, as SRT or WebVTT.

Cues show the narration as written in the spec (never the lexicon's respellings). A
clip's text is split at sentence ends, and long sentences at word boundaries, so a cue
fits in two lines; the clip's time is shared out by character count.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

LINE_CHARS = 42
CUE_CHARS = 2 * LINE_CHARS
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class Narrated:
    """One narration as heard: its text, start and length in the output."""

    text: str
    start_ms: int
    duration_ms: int


@dataclass(frozen=True)
class Cue:
    """One subtitle."""

    start_ms: int
    end_ms: int
    text: str


def split_text(text: str, limit: int = CUE_CHARS) -> list[str]:
    """Sentences of ``text``, with sentences longer than ``limit`` split between words."""
    chunks: list[str] = []
    for sentence in _SENTENCE_END.split(" ".join(text.split())):
        if len(sentence) <= limit:
            chunks.append(sentence)
            continue
        words = sentence.split(" ")
        # Even pieces instead of one full cue and a short leftover.
        pieces = -(-len(sentence) // limit)
        target = len(sentence) / pieces
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and (len(candidate) > limit or len(current) >= target):
                chunks.append(current)
                candidate = word
            current = candidate
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def cues_for(narrations: Iterable[Narrated]) -> list[Cue]:
    """Cues covering each narration, split by :func:`split_text`."""
    cues: list[Cue] = []
    for narrated in sorted(narrations, key=lambda n: n.start_ms):
        chunks = split_text(narrated.text)
        total = sum(len(chunk) for chunk in chunks) or 1
        elapsed = 0
        for chunk in chunks:
            start = narrated.start_ms + narrated.duration_ms * elapsed // total
            elapsed += len(chunk)
            end = narrated.start_ms + narrated.duration_ms * elapsed // total
            cues.append(Cue(start, end, chunk))
    return cues


def _lines(text: str) -> str:
    return "\n".join(textwrap.wrap(text, LINE_CHARS, break_long_words=False, break_on_hyphens=False))


def _timestamp(ms: int, separator: str) -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _span(cue: Cue, separator: str) -> str:
    return f"{_timestamp(cue.start_ms, separator)} --> {_timestamp(cue.end_ms, separator)}"


def to_srt(cues: Sequence[Cue]) -> str:
    """SubRip text."""
    blocks = [f"{index}\n{_span(cue, ',')}\n{_lines(cue.text)}\n" for index, cue in enumerate(cues, 1)]
    return "\n".join(blocks)


def _vtt_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_vtt(cues: Sequence[Cue]) -> str:
    """WebVTT text."""
    blocks = [f"{_span(cue, '.')}\n{_vtt_escape(_lines(cue.text))}\n" for cue in cues]
    return "\n".join(["WEBVTT\n", *blocks])


@dataclass(frozen=True)
class SubtitleFiles:
    """The ``.srt`` and ``.vtt`` beside an output."""

    srt: Path
    vtt: Path

    @classmethod
    def beside(cls, output: Path) -> SubtitleFiles:
        """``demo.mp4`` → ``demo.srt`` and ``demo.vtt``."""
        return cls(output.with_suffix(".srt"), output.with_suffix(".vtt"))

    def write(self, cues: Sequence[Cue]) -> None:
        """Write both files."""
        self.srt.parent.mkdir(parents=True, exist_ok=True)
        self.srt.write_text(to_srt(cues), encoding="utf-8")
        self.vtt.write_text(to_vtt(cues), encoding="utf-8")
