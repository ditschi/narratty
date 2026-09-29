"""Text normalization shared by all providers (and by the audio cache key)."""

from __future__ import annotations

import re
import unicodedata

_REPLACEMENTS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": " - ", "…": "..."})
_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """NFC-normalize, straighten typographic punctuation and collapse whitespace."""
    text = unicodedata.normalize("NFC", text).translate(_REPLACEMENTS)
    return _WHITESPACE.sub(" ", text).strip()
