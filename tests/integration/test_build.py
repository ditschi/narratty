"""The full pipeline with real Piper, VHS and ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.build import WorkspaceOptions, build
from narratty.cli.app import app
from narratty.errors import CommandError
from narratty.render import media
from tests.helpers import plain

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all(shutil.which(tool) for tool in ("vhs", "ttyd", "ffmpeg", "ffprobe")),
        reason="needs vhs, ttyd and ffmpeg",
    ),
]

SPEC = """\
meta: {title: Integration}
terminal: {width: 800, height: 400}
scenes:
  - id: setup
    hidden: true
    actions:
      - type_command: "mkdir -p demo && cd demo && touch one.txt two.txt"
      - enter
  - id: list
    narration: Here are the files in the demo directory.
    actions:
      - type_command: "ls"
      - enter
  - id: quiet
    actions:
      - type_command: "echo \\"it's done\\""
      - enter
      - hold: 700
  - id: wrap
    narration: That is the whole demo.
"""


@pytest.fixture
def spec(tmp_path: Path) -> Path:
    path = tmp_path / "demo.narratty.yaml"
    path.write_text(SPEC, encoding="utf-8")
    return path


def test_build_produces_a_synced_video(spec: Path, tmp_path: Path) -> None:
    result = build(spec, work_dir=tmp_path / "work", workspace=WorkspaceOptions(mode="rw"))
    info = media.probe(result.output)
    assert info.has_video and info.has_audio
    assert abs(result.drift) < 0.05, f"video {result.video_ms} ms vs plan {result.expected_ms} ms"
    assert abs(info.duration_ms - result.video_ms) < 200
    assert [p.scene_id for p in result.placements] == ["list", "wrap"]
    work = tmp_path / "work"
    assert {"scene.tape", "silent.mp4", "narration.wav"} <= {p.name for p in work.iterdir()}
    assert (spec.parent / "demo" / "one.txt").exists(), "rw mode runs in place"


def test_build_command_leaves_the_workspace_alone(spec: Path) -> None:
    result = CliRunner().invoke(app, ["build", str(spec), "-o", str(spec.parent / "out.mp4")])
    assert result.exit_code == 0, result.output
    assert (spec.parent / "out.mp4").is_file()
    assert "planned" in plain(result.output)
    assert not (spec.parent / "demo").exists(), "the default snapshot mode keeps the source untouched"


def test_replay_keeps_shell_state_without_recording_the_scene(tmp_path: Path) -> None:
    from narratty.render.tape import build_tape
    from narratty.spec.loader import parse_spec
    from narratty.timeline import build_timeline

    spec = parse_spec(
        "end_card: false\ntiming: {lead_in_ms: 0, tail_ms: 500}\nscenes:\n"
        "  - id: first\n    actions: [{run: 'export REPLAY_VALUE=ready'}, {hold: 3000}]\n"
        "  - id: second\n    actions: [{run: 'test \"$REPLAY_VALUE\" = ready'}, {hold: 500}]\n",
        tmp_path / "demo.narratty.yaml",
    )
    durations = []
    for replay in (frozenset(), frozenset({"first"})):
        name = "replay" if replay else "full"
        video, tape_path, exits = (tmp_path / f"{name}.{suffix}" for suffix in ("mp4", "tape", "log"))
        tape = build_tape(spec, build_timeline(spec, {}), video, exit_log=exits, replay_scenes=replay)
        tape_path.write_text(tape.text, encoding="utf-8")
        media.run_vhs(tape_path, tmp_path)
        assert '0\ttest "$REPLAY_VALUE" = ready' in exits.read_text(encoding="utf-8")
        durations.append(media.probe(video).duration_ms)
    assert durations[0] - durations[1] > 2500


def test_build_reuses_scene_prefix_and_invalidates_changed_scenes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from narratty.build import Plan
    from narratty.spec import load_spec
    from narratty.timeline import build_timeline

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "demo.narratty.yaml"
    text = (
        "end_card: false\nterminal: {width: 600, height: 300}\nscenes:\n"
        "  - id: first\n    actions: [{run: 'export CACHE_TEST=ready'}, {hold: 800}]\n"
        "  - id: second\n    actions: [{run: 'test \"$CACHE_TEST\" = ready'}, {hold: 800}]\n"
        "  - id: third\n    actions: [{run: 'echo old'}, {hold: 800}]\n"
    )
    path.write_text(text, encoding="utf-8")

    def no_tts(spec_path: Path, **kwargs: object) -> Plan:
        loaded = load_spec(spec_path)
        return Plan(spec_path, loaded, (), build_timeline(loaded, {}))

    monkeypatch.setattr("narratty.build.plan", no_tts)
    options = WorkspaceOptions("rw", allow_dirty=True)
    logs: list[str] = []
    build(path, workspace=options, scene_cache=True, max_drift=0.3, log=logs.append)
    path.write_text(text.replace("echo old", "echo new"), encoding="utf-8")
    work = tmp_path / "work"
    result = build(path, workspace=options, work_dir=work, scene_cache=True, max_drift=0.3, log=logs.append)
    assert any("reusing 2 cached scenes" in line for line in logs)
    assert "# scene: first" not in (work / "scene.tape").read_text(encoding="utf-8")
    assert '0\ttest "$CACHE_TEST" = ready' in (work / "exits.log").read_text(encoding="utf-8")
    assert media.probe(result.output).has_video
    path.write_text(
        text.replace("echo old", "echo newer").replace("CACHE_TEST=ready", "CACHE_TEST=changed"),
        encoding="utf-8",
    )
    logs.clear()
    with pytest.raises(CommandError):
        build(path, workspace=options, scene_cache=True, max_drift=0.3, log=logs.append)
    assert not any("reusing" in line for line in logs)


def _last_frame_white_share(video: Path) -> float:
    frame = subprocess.run(
        ["ffmpeg", "-v", "error", "-sseof", "-1", "-i", str(video), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return sum(1 for value in frame if value > 200) / len(frame)


def test_end_card_shows_the_qr_code(tmp_path: Path) -> None:
    spec = tmp_path / "card.narratty.yaml"
    spec.write_text(
        "terminal: {width: 1200, height: 700}\n"
        "end_card: {duration_ms: 2000}\n"
        "scenes:\n  - id: hi\n    actions: [{type_command: 'echo hi'}, enter, {hold: 500}]\n",
        encoding="utf-8",
    )
    result = build(spec, end_card=True)
    assert abs(result.drift) < 0.05
    assert _last_frame_white_share(result.output) > 0.1, "the white QR code fills the last frame"
    work = tmp_path / "plain"
    plain_result = build(spec, tmp_path / "plain.mp4", work_dir=work, end_card=False)
    assert result.expected_ms - plain_result.expected_ms == 2000
    assert _last_frame_white_share(plain_result.output) < 0.01
    assert "end card" not in (work / "scene.tape").read_text(encoding="utf-8")


EXITS = """\
terminal: {{width: 600, height: 300}}
end_card: false
scenes:
  - id: missing
    narration: This file does not exist.
    expect_exit: {expect}
    actions: [{{type_command: "cat missing.txt"}}, enter]
"""


@pytest.mark.parametrize(("expect", "fails"), [("success", True), ("failure", False), ("any", False)])
def test_build_checks_exit_codes(tmp_path: Path, expect: str, fails: bool) -> None:
    spec = tmp_path / "exits.narratty.yaml"
    spec.write_text(EXITS.format(expect=expect), encoding="utf-8")
    options = WorkspaceOptions(mode="rw")
    if fails:
        with pytest.raises(CommandError, match="`cat missing.txt` exited with 1"):
            build(spec, draft=True, workspace=options)
        assert (tmp_path / "exits.draft.mp4").is_file(), "the video is kept for inspection"
    else:
        build(spec, draft=True, workspace=options)
