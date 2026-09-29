"""Shared test helpers."""

from __future__ import annotations

import math
import re
import wave
from array import array
from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Strip ANSI styling (Typer forces colour on GitHub Actions)."""
    return _ANSI.sub("", text)


def write_tone(path: Path, duration_ms: int, rate: int = 22050) -> Path:
    """Write a quiet sine tone as a 16-bit mono WAV (stands in for synthesized speech)."""
    frames = rate * duration_ms // 1000
    samples = array("h", (int(3000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(frames)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return path
