"""Subtitle cues and their SRT/WebVTT text."""

from __future__ import annotations

from pathlib import Path

from narratty.render.subtitles import (
    CUE_CHARS,
    Cue,
    Narrated,
    SubtitleFiles,
    cues_for,
    split_text,
    to_srt,
    to_vtt,
)

LONG = (
    "This takes a while the first time because every dependency is fetched, "
    "compiled and cached for later runs, which is quite a lot of work."
)


def test_split_at_sentences_and_long_sentences_between_words() -> None:
    chunks = split_text(f"Build it.  Done? {LONG}")
    assert chunks[:2] == ["Build it.", "Done?"]
    assert len(chunks) == 4
    assert all(len(chunk) <= CUE_CHARS for chunk in chunks)
    assert " ".join(chunks[2:]) == LONG


def test_cues_share_the_clip_by_length() -> None:
    cues = cues_for([Narrated("Two words. And four more words.", 1000, 3000)])
    assert cues == [Cue(1000, 2000, "Two words."), Cue(2000, 4000, "And four more words.")]


def test_cues_are_in_time_order() -> None:
    cues = cues_for([Narrated("Second.", 5000, 500), Narrated("First.", 0, 500)])
    assert [cue.text for cue in cues] == ["First.", "Second."]


def test_srt() -> None:
    cues = [Cue(0, 1500, "Hi."), Cue(3_723_004, 3_724_000, LONG[:80])]
    assert to_srt(cues) == (
        "1\n00:00:00,000 --> 00:00:01,500\nHi.\n\n"
        "2\n01:02:03,004 --> 01:02:04,000\n"
        "This takes a while the first time because\nevery dependency is fetched, compiled\n"
    )


def test_vtt_escapes_markup() -> None:
    assert to_vtt([Cue(0, 1500, "Pipe a < b & c.")]) == (
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nPipe a &lt; b &amp; c.\n"
    )


def test_files_beside_the_output(tmp_path: Path) -> None:
    files = SubtitleFiles.beside(tmp_path / "out" / "demo.draft.mp4")
    assert files == SubtitleFiles(tmp_path / "out" / "demo.draft.srt", tmp_path / "out" / "demo.draft.vtt")
    files.write([Cue(0, 1000, "Hi.")])
    assert files.srt.read_text(encoding="utf-8").startswith("1\n")
    assert files.vtt.read_text(encoding="utf-8").startswith("WEBVTT")
