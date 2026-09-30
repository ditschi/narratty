"""Draft builds: estimated narration lengths instead of TTS, half size, low frame rate.

A draft shows where things happen in seconds instead of minutes: the timeline is
computed from a length estimate, the video is silent and the narration is burned in
as subtitles.
"""

from __future__ import annotations

from narratty.spec.model import Spec
from narratty.tts.normalize import normalize_text

FRAMERATE = 10
# Roughly Kokoro's and Piper's pace at speed 1.0.
CHARS_PER_SECOND = 14.0


def speaking_rate(spec: Spec) -> float:
    """The spec's speed setting as a factor (2.0 = twice as fast)."""
    if spec.tts.provider == "piper":
        return 1.0 / spec.tts.piper.length_scale
    if spec.tts.provider == "kokoro":
        return spec.tts.kokoro.speed
    return 1.0


def estimate_ms(text: str, rate: float = 1.0) -> int:
    """Estimated spoken length of ``text``."""
    return round(len(normalize_text(text)) / (CHARS_PER_SECOND * rate) * 1000)


def estimated_audio_ms(spec: Spec) -> dict[str, int]:
    """Estimated narration length of each narrated scene."""
    rate = speaking_rate(spec)
    return {scene.id: estimate_ms(scene.narration or "", rate) for scene in spec.narrated_scenes}


def draft_spec(spec: Spec) -> Spec:
    """``spec`` with the terminal at half size (same layout, a quarter of the pixels)."""
    term = spec.terminal
    smaller = term.model_copy(
        update={
            "width": max(100, term.width // 2),
            "height": max(100, term.height // 2),
            "font_size": max(6, term.font_size // 2),
        }
    )
    return spec.model_copy(update={"terminal": smaller})
