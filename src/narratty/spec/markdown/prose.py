"""Key points of paragraphs, shown on prose slides (``prose: slides``)."""

from __future__ import annotations

import re
from collections.abc import Iterator

MAX_POINT = 75
"""A first sentence longer than this (in characters, without backticks) is cut."""
MIN_CUT = 25
"""It is cut no earlier than this, so the point keeps its subject."""
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_CUTS = (", ", "; ", ": ")


def key_point(source: str) -> str:
    """The key point of a paragraph, from its inline Markdown.

    The first sentence without parentheses; when long, cut at the first comma, semicolon
    or colon after :data:`MIN_CUT` characters. Inline code is never split.
    """
    text = " ".join(_LINK.sub(r"\1", source).split())
    sentence = _without_parentheses(_first_sentence(text))
    if _width(sentence) > MAX_POINT:
        for at in _outside_code(sentence):
            if sentence[at : at + 2] in _CUTS and _width(sentence[:at]) >= MIN_CUT:
                sentence = sentence[:at]
                break
    return sentence.rstrip(" .:;,") or text


def _outside_code(text: str) -> Iterator[int]:
    """The indexes of ``text`` outside inline code."""
    inside = False
    for at, char in enumerate(text):
        if char == "`":
            inside = not inside
        elif not inside:
            yield at


def _first_sentence(text: str) -> str:
    for at in _outside_code(text):
        if text[at] in ".!?" and text[at + 1 : at + 2] == " " and text[at + 2 : at + 3][:1].isupper():
            return text[: at + 1]
    return text


def _without_parentheses(text: str) -> str:
    """``text`` without ``( … )`` outside inline code."""
    kept, depth, start = [], 0, 0
    outside = set(_outside_code(text))
    for at, char in enumerate(text):
        if at not in outside:
            continue
        if char == "(":
            if depth == 0:
                kept.append(text[start:at].rstrip())
            depth += 1
        elif char == ")" and depth:
            depth -= 1
            if depth == 0:
                start = at + 1
    if depth:
        return text
    kept.append(text[start:])
    return re.sub(r"\s+([,.;:])", r"\1", " ".join(" ".join(kept).split()))


def _width(text: str) -> int:
    return len(text.replace("`", ""))
