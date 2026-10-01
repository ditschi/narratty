"""Piper provider.

Piper (``piper-tts``) is GPL-3.0, so narratty runs it as a subprocess
(``python -m piper``) instead of importing it; see the design's licensing note.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from narratty.errors import MissingDependencyError, RenderError
from narratty.tts import catalog
from narratty.tts.base import VoiceInfo, package_version, unknown_voice_error
from narratty.tts.download import download

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603


def find_piper() -> list[str] | None:
    """The command that runs Piper: this interpreter's module, else ``piper`` on PATH."""
    if importlib.util.find_spec("piper") is not None:
        return [sys.executable, "-m", "piper"]
    if path := shutil.which("piper"):
        return [path]
    return None


class PiperProvider:
    """Synthesizes with Piper; voices live in ``<data>/piper`` as ``<id>.onnx`` + ``.onnx.json``."""

    name = "piper"
    # Each clip is its own process, which spends most of its time loading the voice.
    concurrency = min(4, os.cpu_count() or 1)

    def __init__(
        self,
        voice_dir: Path,
        *,
        command: list[str] | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.voice_dir = voice_dir
        self._command = command
        self._runner = runner or _run

    def _piper(self) -> list[str] | None:
        return self._command if self._command is not None else find_piper()

    def unavailable_reason(self) -> str | None:
        if self._piper() is None:
            return "Piper is not installed (pip package piper-tts)"
        return None

    def model_path(self, voice: str) -> Path:
        return self.voice_dir / f"{voice}.onnx"

    def config_path(self, voice: str) -> Path:
        return self.voice_dir / f"{voice}.onnx.json"

    def is_installed(self, voice: str) -> bool:
        return self.model_path(voice).is_file() and self.config_path(voice).is_file()

    def _local_voices(self) -> list[str]:
        if not self.voice_dir.is_dir():
            return []
        return sorted(p.name.removesuffix(".onnx") for p in self.voice_dir.glob("*.onnx"))

    def voices(self) -> list[VoiceInfo]:
        curated = catalog.voices(self.name)
        result = [
            VoiceInfo(self.name, v.id, v.description, v.language, self.is_installed(v.id)) for v in curated
        ]
        known = {v.id for v in curated}
        for voice in self._local_voices():
            if voice not in known and self.is_installed(voice):
                language = voice.split("-", 1)[0]
                result.append(VoiceInfo(self.name, voice, "installed locally", language, True, curated=False))
        return result

    def install(self, voice: str, *, show_progress: bool = True) -> None:
        if voice not in catalog.voice_ids(self.name):
            if self.is_installed(voice):
                return
            raise unknown_voice_error(self, voice)
        for file in catalog.piper_files(voice):
            download(file, self.voice_dir, show_progress=show_progress)

    def model_version(self, voice: str) -> str:
        config = hashlib.sha256(self.config_path(voice).read_bytes()).hexdigest()[:16]
        return f"piper-tts {package_version('piper-tts')}; config {config}"

    def synthesize(self, text: str, voice: str, out: Path, options: Mapping[str, Any]) -> None:
        piper = self._piper()
        if piper is None:
            raise MissingDependencyError(
                "Piper is not installed", hint="Install it with `pip install piper-tts`."
            )
        with tempfile.TemporaryDirectory(prefix="narratty-piper-") as tmp:
            text_file = Path(tmp) / "input.txt"
            text_file.write_text(text + "\n", encoding="utf-8")
            argv = [
                *piper,
                "--model",
                str(self.model_path(voice)),
                "--config",
                str(self.config_path(voice)),
                "--input-file",
                str(text_file),
                "--output-file",
                str(out),
                "--length-scale",
                str(options.get("length_scale", 1.0)),
                "--sentence-silence",
                str(options.get("sentence_silence", 0.2)),
            ]
            result = self._runner(argv)
        if result.returncode != 0 or not out.is_file():
            detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
            raise RenderError(f"Piper failed for voice {voice!r}: {detail[0]}")
