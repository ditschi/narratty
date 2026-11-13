"""Pipeline glue: output names, clip placement and verification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from narratty.build import (
    BuildResult,
    CastOutputs,
    Plan,
    default_output,
    place_clips,
    place_clips_at,
    unmasked,
    verify,
)
from narratty.errors import RenderError, SyncError
from narratty.render import media
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline
from narratty.tts.synth import Clip


@pytest.mark.parametrize(
    ("spec", "suffix", "expected"),
    [
        ("d/demo.narratty.yaml", ".mp4", "d/demo.mp4"),
        ("demo.narratty.yml", ".silent.mp4", "demo.silent.mp4"),
        ("tour.yaml", ".mp4", "tour.mp4"),
        ("odd.txt", ".mp4", "odd.mp4"),
    ],
)
def test_default_output(spec: str, suffix: str, expected: str) -> None:
    assert default_output(Path(spec), suffix) == Path(expected)


def _plan(tmp_path: Path) -> Plan:
    spec = parse_spec(
        "timing: {lead_in_ms: 0, tail_ms: 0}\nscenes:\n"
        "  - id: a\n    narration: One.\n  - id: b\n    narration: Two.\n",
        tmp_path / "s.narratty.yaml",
    )
    clips = (Clip("a", tmp_path / "a.wav", 1500, False), Clip("b", tmp_path / "b.wav", 500, False))
    timeline = build_timeline(spec, {c.scene_id: c.duration_ms for c in clips})
    return Plan(tmp_path / "s.narratty.yaml", spec, clips, timeline)


def test_place_clips_scales_with_the_rendered_length(tmp_path: Path) -> None:
    planned = _plan(tmp_path)
    assert planned.timeline.total_ms == 3000
    assert [p.start_ms for p in place_clips(planned, 3000)] == [0, 2000]
    assert [p.start_ms for p in place_clips(planned, 2940)] == [0, 1960]


def test_place_clips_at_recorded_scene_starts(tmp_path: Path) -> None:
    assert [p.start_ms for p in place_clips_at(_plan(tmp_path), {"a": 10, "b": 2500})] == [10, 2500]


def test_cast_outputs_sit_beside_the_page() -> None:
    outputs = CastOutputs(Path("out/demo.html"))
    assert (outputs.cast, outputs.audio) == (Path("out/demo.cast"), Path("out/demo.mp3"))


def test_workspace_is_relative_to_the_spec(tmp_path: Path) -> None:
    assert _plan(tmp_path).workspace_source == tmp_path.resolve()


def _result(tmp_path: Path, video_ms: int) -> BuildResult:
    return BuildResult(tmp_path / "o.mp4", 10000, video_ms, ())


def test_verify_accepts_small_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(9700, True, True))
    verify(_result(tmp_path, 9700), max_drift=0.1)


def test_verify_rejects_large_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(13000, True, True))
    with pytest.raises(SyncError, match=r"\+30%") as raised:
        verify(_result(tmp_path, 13000), max_drift=0.1)
    assert raised.value.hint and "took longer" in raised.value.hint


def test_a_shorter_video_blames_dropped_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(8000, True, True))
    monkeypatch.setattr(media.os, "getloadavg", lambda: (7.25, 5.0, 3.0))
    with pytest.raises(SyncError, match=r"-20%") as raised:
        verify(_result(tmp_path, 8000), max_drift=0.1)
    hint = raised.value.hint or ""
    assert "took longer" not in hint
    assert "dropped frames" in hint and "load average 7.2" in hint


def test_verify_needs_both_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(10000, True, False))
    with pytest.raises(RenderError, match="audio stream"):
        verify(_result(tmp_path, 10000), max_drift=0.1)


def _env_plan(tmp_path: Path) -> Plan:
    spec_path = tmp_path / "s.narratty.yaml"
    spec = parse_spec("environment: {image: acme/dev:1}\nscenes: [{id: a}]\n", spec_path)
    return Plan(spec_path, spec, (), build_timeline(spec, {}))


def test_environment_bridge_natively(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import contextmanager

    from narratty.build import environment_bridge
    from narratty.environment import Session
    from narratty.workspace import PreparedWorkspace

    started: list[dict[str, object]] = []

    @contextmanager
    def fake_provide(environment: object, spec: object, **kwargs: object):  # type: ignore[no-untyped-def]
        started.append(kwargs)
        yield Session("podman", "env-1", "/work")

    monkeypatch.setattr("narratty.env_provide.provide", fake_provide)
    monkeypatch.setattr("narratty.runtime.container_engine", lambda: "podman")
    monkeypatch.setattr("narratty.environment.running", lambda engine, spec_path: None)
    workspace = PreparedWorkspace(tmp_path, "rw", tmp_path)
    logged: list[str] = []
    with environment_bridge(_env_plan(tmp_path), workspace, None, logged.append) as bridge:
        assert bridge is not None
        assert bridge[:2] == ["podman", "exec"] and bridge[-1] == "env-1"
    assert started[0]["with_agent"] is False and started[0]["engine"] == "podman"
    assert any("--runtime native" in line and "--no-env" in line for line in logged), (
        "a native run says why it still starts a container"
    )


def test_environment_bridge_reuses_a_kept_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from narratty.build import environment_bridge
    from narratty.environment import Session
    from narratty.workspace import PreparedWorkspace

    kept = Session("docker", "narratty-env-abc", "/work")
    monkeypatch.setattr("narratty.runtime.container_engine", lambda: "docker")
    monkeypatch.setattr("narratty.environment.running", lambda engine, spec_path: (kept, tmp_path))
    monkeypatch.setattr("narratty.env_provide.provide", lambda *a, **k: pytest.fail("started another"))
    workspace = PreparedWorkspace(tmp_path, "rw", tmp_path)
    with environment_bridge(_env_plan(tmp_path), workspace, None) as bridge:
        assert bridge == kept.exec_bridge()


def test_environment_bridge_in_the_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from narratty.bridge import BRIDGE_ENV, encode
    from narratty.build import environment_bridge
    from narratty.workspace import PreparedWorkspace

    workspace = PreparedWorkspace(tmp_path, "rw", tmp_path)
    monkeypatch.setenv("NARRATTY_IN_CONTAINER", "1")
    with environment_bridge(_env_plan(tmp_path), workspace, None) as bridge:
        assert bridge is None, "the host ran it with --no-env"
    monkeypatch.setenv(BRIDGE_ENV, encode(["narratty-agent", "connect"]))
    with environment_bridge(_env_plan(tmp_path), workspace, None) as bridge:
        assert bridge == ["narratty-agent", "connect"]


class FakeMedia:
    """VHS, ffprobe and ffmpeg replaced; records what mux was asked to do."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, video_ms: int) -> None:
        self.mux_kwargs: dict[str, object] = {}
        self.render_kwargs: dict[str, object] = {}
        self.srt = ""
        monkeypatch.setattr("narratty.build.render_silent", self._render)
        monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(video_ms, True, True))
        monkeypatch.setattr(media, "mux", self._mux)

    def _render(
        self, planned: Plan, video: Path, work: Path, workspace: Path, bridge: object = None, **kwargs: object
    ) -> None:
        self.render_kwargs = kwargs
        video.write_bytes(b"mp4")

    def _mux(self, video: Path, audio: Path, out: Path, **kwargs: object) -> None:
        self.mux_kwargs = kwargs
        subtitles = kwargs.get("subtitles")
        if isinstance(subtitles, Path):
            self.srt = subtitles.read_text(encoding="utf-8")
        out.write_bytes(b"mp4")


DRAFT_SPEC = (
    "end_card: false\ntiming: {lead_in_ms: 0, tail_ms: 0}\nscenes: [{id: a, narration: Hello there.}]\n"
)


def test_draft_build_burns_in_the_narration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from narratty.build import WorkspaceOptions, build
    from narratty.draft import estimate_ms

    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(DRAFT_SPEC, encoding="utf-8")
    planned_ms = estimate_ms("Hello there.") + 500
    fake = FakeMedia(monkeypatch, planned_ms)
    result = build(spec, draft=True, workspace=WorkspaceOptions("rw", allow_dirty=True))
    assert result.output == tmp_path / "demo.draft.mp4"
    assert fake.mux_kwargs == {
        "subtitles": fake.mux_kwargs["subtitles"],
        "burn": True,
        "overlays": [],
        "fast": True,
    }
    assert fake.render_kwargs["fast"] is True  # a draft fills its pauses with still frames
    assert "Hello there." in fake.srt


def test_build_scene_cache_reuses_prefix_and_invalidates_changed_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from narratty.build import WorkspaceOptions, build
    from narratty.render.timelapse import Layout

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    planned = _plan(workspace)
    monkeypatch.setenv("NARRATTY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("narratty.build.plan", lambda *args, **kwargs: planned)
    monkeypatch.setattr("narratty.build.build_track", lambda placements, *_: placements)
    fake = FakeMedia(monkeypatch, 3000)
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(3000, True, True, 29.97))
    calls: list[dict[str, Any]] = []

    def render(plan: Plan, video: Path, *args: Any, **kwargs: Any) -> Layout:
        calls.append(kwargs)
        video.write_bytes(b"joined" if kwargs["cached_prefix"] else b"video")
        if kwargs["cached_prefix"]:
            fresh = kwargs["fresh"]
            fresh.video = video.with_name("recording.mp4")
            fresh.video.write_bytes(b"fresh")
            fresh.positions = {"scene-b": 400, "cue-end": 1400}
        return Layout((), {"a": 0, "b": 2000}, {"a": 0, "b": 0}, {"end": 3000})

    monkeypatch.setattr("narratty.build.render_silent", render)
    options = WorkspaceOptions("rw", allow_dirty=True)
    build(planned.spec_path, scene_cache=True, workspace=options)
    build(planned.spec_path, scene_cache=True, workspace=options)
    assert calls[0]["cached_prefix"] is None
    assert calls[1]["replay_scenes"] == frozenset({"a"})
    assert calls[1]["cached_prefix"] is not None
    from narratty.render.scene_cache import SceneCache

    videos = (SceneCache(tmp_path / "cache").root / "videos").glob("*.mp4")
    assert sorted(path.read_bytes() for path in videos) == [b"fresh", b"video"], "joins are not stored"
    assert [part.video.read_bytes() for part in calls[1]["cached_prefix"].parts] == [b"video"]
    build(planned.spec_path, scene_cache=True, refresh_scene_cache=True, workspace=options)
    assert calls[2]["cached_prefix"] is None
    changed = planned.spec.scenes[0].model_copy(update={"pause_ms": 700})
    planned = replace(
        planned, spec=planned.spec.model_copy(update={"scenes": [changed, planned.spec.scenes[1]]})
    )
    build(planned.spec_path, scene_cache=True, workspace=options)
    assert calls[3]["cached_prefix"] is None
    assert fake.mux_kwargs["burn"] is False


def test_build_survives_a_scene_cache_it_cannot_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from narratty.build import WorkspaceOptions, build
    from narratty.render.scene_cache import SceneCache
    from narratty.render.timelapse import Layout

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    planned = _plan(workspace)
    monkeypatch.setenv("NARRATTY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("narratty.build.plan", lambda *args, **kwargs: planned)
    monkeypatch.setattr("narratty.build.build_track", lambda placements, *_: placements)
    FakeMedia(monkeypatch, 3000)
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(3000, True, True, 30))

    def render(plan: Plan, video: Path, *args: Any, **kwargs: Any) -> Layout:
        video.write_bytes(b"video")
        return Layout((), {"a": 0, "b": 2000}, {"a": 0, "b": 0}, {"end": 3000})

    def read_only(*args: Any, **kwargs: Any) -> None:
        raise PermissionError(13, "Permission denied", "/cache/scenes/videos")

    monkeypatch.setattr("narratty.build.render_silent", render)
    monkeypatch.setattr(SceneCache, "put", read_only)
    logs: list[str] = []
    result = build(
        planned.spec_path,
        scene_cache=True,
        workspace=WorkspaceOptions("rw", allow_dirty=True),
        log=logs.append,
    )
    assert result.output.name.endswith(".mp4")
    assert any(line.startswith("scene cache not updated: ") for line in logs), logs


def test_scene_cache_is_off_for_native_snapshots(tmp_path: Path) -> None:
    from narratty.build import _scene_cache_plan
    from narratty.workspace import PreparedWorkspace

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    planned = _plan(workspace)
    snapshot = PreparedWorkspace(tmp_path / "snap" / "workspace", "snapshot", workspace, tmp_path / "snap")
    logs: list[str] = []
    work = tmp_path / "work"
    plan = _scene_cache_plan(
        planned, snapshot, tmp_path / "o.mp4", work, None, fast=False, refresh=False, log=logs.append
    )
    assert plan is None
    assert any("new path each build" in line for line in logs), logs


def test_subtitle_files_show_the_spec_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from narratty.build import WorkspaceOptions, build
    from narratty.draft import estimate_ms

    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(
        DRAFT_SPEC.replace("end_card: false", "end_card: false\nsubtitles: track"), encoding="utf-8"
    )
    fake = FakeMedia(monkeypatch, estimate_ms("Hello there.") + 500)
    build(spec, draft=True, subtitles="files", workspace=WorkspaceOptions("rw", allow_dirty=True))
    assert fake.mux_kwargs["subtitles"] is None
    vtt = (tmp_path / "demo.draft.vtt").read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT") and "Hello there." in vtt
    assert (tmp_path / "demo.draft.srt").is_file()


@pytest.mark.parametrize(("spec_mode", "override", "draft", "expected"), [
    ("none", None, False, "none"),
    ("track", None, False, "track"),
    ("track", None, True, "burn"),
    ("track", "files", True, "files"),
])  # fmt: skip
def test_subtitle_mode(
    spec_mode: str, override: str | None, draft: bool, expected: str, tmp_path: Path
) -> None:
    from dataclasses import replace

    from narratty.build import subtitle_mode

    planned = _plan(tmp_path)
    planned = replace(planned, spec=planned.spec.model_copy(update={"subtitles": spec_mode}), draft=draft)
    assert subtitle_mode(planned, override) == expected


def test_narrations_use_the_clip_lengths(tmp_path: Path) -> None:
    from narratty.build import narrations
    from narratty.render.subtitles import Narrated

    assert narrations(_plan(tmp_path), {"a": 0, "b": 2100}) == [
        Narrated("One.", 0, 1500),
        Narrated("Two.", 2100, 500),
    ]


class FakeVhs:
    """VHS that prints each tape command a second apart, plus ffprobe/ffmpeg for the stills."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, freezes: list[tuple[int, int | None]]) -> None:
        self.repeated: list[tuple[int, int]] = []
        self.recorded_ms = 0
        monkeypatch.setattr(media, "run_vhs", self._run)
        monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(self.recorded_ms, True, False, 25.0))
        monkeypatch.setattr(media, "freezes", lambda path: freezes)
        monkeypatch.setattr(media, "repeat_frames", self._repeat)

    def _run(self, tape: Path, cwd: Path, **kwargs: Any) -> list[media.LogLine]:
        lines = [line for line in tape.read_text(encoding="utf-8").splitlines() if line and line[0] != "#"]
        output = Path(json.loads(lines[0].removeprefix("Output ")))
        output.write_bytes(b"mp4")
        printed = [
            media.LogLine(float(i), line.replace("@", " ").replace("+", " ").replace('"', ""))
            for i, line in enumerate(lines)
        ]
        self.recorded_ms = 1000 * (len(lines) - 2)  # the settings print at once
        log = [media.LogLine(0.0, "File: t.tape"), media.LogLine(0.0, ""), *printed]
        log.append(media.LogLine(float(len(lines)), "Creating ..."))
        for line in log:
            if kwargs.get("on_line"):
                kwargs["on_line"](line, 0)
        return log

    def _repeat(self, video: Path, inserts: list[tuple[int, int]], out: Path, **kwargs: Any) -> None:
        self.repeated = inserts
        out.write_bytes(b"mp4")


FAST_SPEC = (
    "end_card: false\ntiming: {lead_in_ms: 0, tail_ms: 0, narration_buffer_ms: 0}\n"
    "scenes: [{id: a, narration: Hello there and welcome to this rather long narration.,\n"
    "  actions: [{type_command: ls}, enter]}]\n"
)


def _fast_render(
    tmp_path: Path, *, draft: bool, logs: list[str] | None = None, text: str = FAST_SPEC
) -> Path:
    """Render with ``--fast``; returns the video."""
    import dataclasses

    from narratty.build import plan, render_silent

    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(text, encoding="utf-8")
    planned = dataclasses.replace(plan(spec, draft=True), draft=draft)
    work = tmp_path / "work"
    work.mkdir()
    video = tmp_path / "v.mp4"
    render_silent(planned, video, work, tmp_path, fast=True, log=None if logs is None else logs.append)
    return video


def test_fast_render_repeats_frames_of_still_pauses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeVhs(monkeypatch, [(0, None)])
    video = _fast_render(tmp_path, draft=False)
    assert video.read_bytes() == b"mp4"
    assert "Sleep 1000ms" in (tmp_path / "work" / "scene.tape").read_text(encoding="utf-8")
    [(frame, count)] = fake.repeated
    assert count > 0 and frame >= 0


def test_cached_prefix_is_joined_to_fresh_scenes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from narratty.build import FreshFootage, plan, render_silent
    from narratty.render.scene_cache import Footage, SceneRecording

    FakeVhs(monkeypatch, [])
    joined: list[Any] = []

    def join(parts: Any, out: Path, **kwargs: Any) -> None:
        joined.extend(parts)
        out.write_bytes(b"joined")

    monkeypatch.setattr(media, "join_recordings", join)
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(
        "end_card: false\nscenes:\n  - id: a\n    actions: [{run: 'echo a'}]\n"
        "  - id: b\n    actions: [{run: 'echo b'}]\n",
        encoding="utf-8",
    )
    planned = plan(spec, draft=True)
    work = tmp_path / "work"
    work.mkdir()
    first, second = Footage(tmp_path / "old.mp4", 0, 1000), Footage(tmp_path / "older.mp4", 500, 1500)
    previous = SceneRecording((first, second), {"a": 300}, 2000)
    fresh = FreshFootage()
    layout = render_silent(
        planned,
        tmp_path / "silent.mp4",
        work,
        tmp_path,
        cache_markers=True,
        cached_prefix=previous,
        replay_scenes=frozenset({"a"}),
        fresh=fresh,
    )
    assert layout is not None
    assert layout.scene_starts_ms["a"] == 300
    assert layout.scene_starts_ms["b"] == 2000
    assert (tmp_path / "silent.mp4").read_bytes() == b"joined"
    assert [part[0] for part in joined] == [first.video, second.video, fresh.video]
    assert fresh.video == work / "recording.mp4" and "scene-b" in fresh.positions


def test_fast_render_fails_when_a_pause_kept_changing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeVhs(monkeypatch, [])
    with pytest.raises(RenderError, match="not still at the end of a pause in: a"):
        _fast_render(tmp_path, draft=False)


def test_fast_draft_only_logs_a_changing_pause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeVhs(monkeypatch, [])
    logs: list[str] = []
    _fast_render(tmp_path, draft=True, logs=logs)
    assert any("pause in: a" in line for line in logs)
    assert len(fake.repeated) == 1, "the draft keeps its timing"


def test_fast_render_places_cues_after_the_filled_pauses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    from narratty.build import plan, render_silent
    from narratty.render import pauses

    fake = FakeVhs(monkeypatch, [(0, None)])
    monkeypatch.setattr(Path, "replace", lambda self, target: target)
    recorded: dict[str, dict[str, int]] = {}
    shift = pauses.shift_positions

    def spy(positions: dict[str, int], *args: Any) -> dict[str, int]:
        recorded["positions"] = dict(positions)
        return shift(positions, *args)

    monkeypatch.setattr(pauses, "shift_positions", spy)
    spec = tmp_path / "demo.narratty.yaml"
    actions = "enter, {overlay: Before}, {hold: auto}, {overlay: After}]}]"
    spec.write_text(FAST_SPEC.replace("enter]}]", actions), encoding="utf-8")
    planned = dataclasses.replace(plan(spec, draft=True), draft=False)
    work = tmp_path / "work"
    work.mkdir()
    layout = render_silent(planned, tmp_path / "v.mp4", work, tmp_path, fast=True)
    assert layout is not None and not layout.segments
    [(_, count)] = fake.repeated
    filled_ms = count * 40  # 25 fps
    before, after = layout.cues_ms["overlay:a:2"], layout.cues_ms["overlay:a:4"]
    raw = recorded["positions"]
    assert before == raw["cue-overlay:a:2"], "before the pause: unchanged"
    assert after == raw["cue-overlay:a:4"] + filled_ms, "after the pause: later by the filled frames"


def test_exit_log_in_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from narratty.build import REMOTE_EXIT_LOG_ENV, collect_exit_log, fresh_exit_log

    (tmp_path / "exits.log").write_text("stale", encoding="utf-8")
    remote = fresh_exit_log(tmp_path, ["docker", "exec", "-it", "dev"])
    assert str(remote).startswith("/tmp/narratty-exits-") and not (tmp_path / "exits.log").exists()
    monkeypatch.setenv(REMOTE_EXIT_LOG_ENV, "/tmp/given.log")
    assert fresh_exit_log(tmp_path, ["narratty-agent", "connect"]) == Path("/tmp/given.log")

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "0\tls\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    collect_exit_log(["narratty-agent", "connect", "--"], remote, tmp_path)
    assert calls == [], "the agent cannot read files; the host does"
    collect_exit_log(["docker", "exec", "--interactive", "--tty", "--workdir", "/w", "dev"], remote, tmp_path)
    [argv] = calls
    assert argv[:5] == ["docker", "exec", "--workdir", "/w", "dev"], "no terminal for reading a file"
    assert argv[5:7] == ["sh", "-c"] and str(remote) in argv[7]
    assert (tmp_path / "exits.log").read_text(encoding="utf-8") == "0\tls\n"


def test_a_scene_can_opt_out_of_fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeVhs(monkeypatch, [(0, None)])
    _fast_render(tmp_path, draft=False, text=FAST_SPEC.replace("{id: a,", "{id: a, fast: false,"))
    assert fake.repeated == [], "the scene's pause was recorded in full"


def test_a_scene_can_opt_in_to_fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses

    from narratty.build import plan, render_silent

    fake = FakeVhs(monkeypatch, [(0, None)])
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(FAST_SPEC.replace("{id: a,", "{id: a, fast: true,"), encoding="utf-8")
    planned = dataclasses.replace(plan(spec, draft=True), draft=False)
    (tmp_path / "work").mkdir()
    render_silent(planned, tmp_path / "v.mp4", tmp_path / "work", tmp_path)
    assert fake.repeated, "filled without --fast"


def test_check_runs_masked_commands_as_they_are() -> None:
    spec = parse_spec(
        "scenes:\n  - id: a\n    actions:\n"
        "      - {run: make, show: make all, max_lines: 3}\n      - run: ls\n",
        Path("t.narratty.yaml"),
    )
    plain = unmasked(spec).scenes[0].actions
    assert plain[0].model_dump(exclude_none=True) == {"run": "make"}
    assert plain[1] is spec.scenes[0].actions[1]


def test_a_shown_command_takes_the_time_of_its_typing() -> None:
    spec = parse_spec(
        "timing: {run_hold_ms: 0}\nterminal: {typing_speed_ms: 10}\n"
        "scenes:\n  - id: a\n    actions: [{run: a-long-substitute, show: ab}]\n",
        Path("t.narratty.yaml"),
    )
    assert build_timeline(spec, {}).scene("a").action_ms == 30


def test_verify_judges_per_scene_placement_by_its_overruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from narratty.sync import Overrun

    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(20000, True, True))
    aligned = replace(_result(tmp_path, 20000), overruns=())
    verify(aligned, max_drift=0.1)  # twice as long as planned, but every narration fits its scene
    clipped = replace(aligned, overruns=(Overrun("intro", 800, 4000, 5000, 4200),))
    with pytest.raises(SyncError, match=r"intro \(0.80s over: scene recorded 0.80s shorter than planned\)"):
        verify(clipped, max_drift=0.1)
    verify(clipped, max_drift=0.25)


def test_aligned_starts_use_the_recorded_scene_starts(tmp_path: Path) -> None:
    from narratty.build import aligned_starts

    assert aligned_starts(_plan(tmp_path), {"a": 40, "b": 4000}) == {"a": 40, "b": 4000}


def test_render_stretches_a_recording_that_dropped_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from narratty.build import plan, render_silent
    from narratty.render import timelapse

    fake = FakeVhs(monkeypatch, [])
    took: list[int] = []
    stretched: list[float] = []

    def run_vhs(tape: Path, cwd: Path, **kwargs: Any) -> list[media.LogLine]:
        log = fake._run(tape, cwd, **kwargs)
        took.append(timelapse.recorded_ms(log))
        return log

    def probe(path: Path) -> media.MediaInfo:
        # VHS wrote 80% of the recorded time; the stretched copy has all of it.
        duration = took[0] if path.name == "retimed.mp4" else took[0] * 8 // 10
        return media.MediaInfo(duration, True, False, 30.0)

    def retime(video: Path, factor: float, out: Path, **kwargs: Any) -> None:
        stretched.append(factor)
        out.write_bytes(b"retimed")

    monkeypatch.setattr(media, "run_vhs", run_vhs)
    monkeypatch.setattr(media, "probe", probe)
    monkeypatch.setattr(timelapse, "retime", retime)
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(
        "end_card: false\nscenes:\n  - id: a\n    narration: One.\n    actions: [{run: 'echo a'}]\n"
        "  - id: b\n    actions: [{run: 'echo b'}]\n",
        encoding="utf-8",
    )
    work = tmp_path / "work"
    work.mkdir()
    logs: list[str] = []
    layout = render_silent(plan(spec, draft=True), tmp_path / "v.mp4", work, tmp_path, log=logs.append)
    assert stretched == [pytest.approx(1.25)]
    assert any("dropped frames" in line for line in logs)
    assert layout is not None and set(layout.scene_starts_ms) == {"a", "b"}
    assert (tmp_path / "v.mp4").read_bytes() == b"retimed"


NATIVE_HIDDEN = "end_card: false\nscenes:\n  - id: setup\n    hidden: true\n    actions: [{run: '%s'}]\n"


def test_native_hidden_commands_are_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    from narratty.build import guard_native_hidden

    monkeypatch.delenv("NARRATTY_IN_CONTAINER", raising=False)
    said: list[str] = []
    guard_native_hidden(parse_spec(NATIVE_HIDDEN % "cd demo", Path("t.narratty.yaml")), said.append)
    assert len(said) == 1 and "hidden commands run on this machine" in said[0]
    said.clear()
    guard_native_hidden(
        parse_spec("end_card: false\nscenes:\n  - id: a\n", Path("t.narratty.yaml")), said.append
    )
    assert said == []


@pytest.mark.parametrize(
    "command",
    ["git config --global user.name Demo", "echo x >> ~/.bashrc", "rm -rf $HOME/.cache/x", "cp a ${HOME}/b"],
)
def test_native_hidden_commands_that_change_home_need_yes(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    from narratty.build import guard_native_hidden
    from narratty.container import SandboxRequest
    from narratty.errors import UsageError

    monkeypatch.delenv("NARRATTY_IN_CONTAINER", raising=False)
    spec = parse_spec(NATIVE_HIDDEN % command, Path("t.narratty.yaml"))
    with pytest.raises(UsageError, match="hidden command in scene 'setup' would change your home") as raised:
        guard_native_hidden(spec, lambda _: None)
    assert command not in raised.value.message, "hidden commands may hold secrets"
    guard_native_hidden(spec, lambda _: None, SandboxRequest(assume_yes=True))
    monkeypatch.setenv("NARRATTY_IN_CONTAINER", "1")
    guard_native_hidden(spec, lambda _: None)
