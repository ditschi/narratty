"""Small WAV helpers built on the standard library."""

from __future__ import annotations

import wave
from array import array
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def wav_duration_ms(path: Path) -> int:
    """Length of a WAV file in whole milliseconds (rounded up)."""
    with wave.open(str(path), "rb") as wav:
        frames, rate = wav.getnframes(), wav.getframerate()
    return -(-frames * 1000 // rate)


def write_wav(path: Path, samples: Iterable[float] | Any, rate: int) -> None:
    """Write mono float samples in ``[-1, 1]`` as 16-bit PCM."""
    if hasattr(samples, "clip") and hasattr(samples, "astype"):  # numpy array: vectorized
        pcm: bytes = (samples.clip(-1.0, 1.0) * 32767).astype("<i2").tobytes()
    else:
        pcm = array("h", (round(max(-1.0, min(1.0, s)) * 32767) for s in samples)).tobytes()
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
