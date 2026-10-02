"""Incremental builds: record only the scenes that changed, reuse the rest.

The tape is split into sections (``narratty.render.script.sections``): setup, lead-in
(``HEAD``), each scene, tail and end card (``TAIL``). Each section's key hashes its tape
lines together with the key of the section before it, so a change re-records that
section and everything after it, and an unchanged prefix comes from the cache. Pauses
shortened by ``fast`` read the same whatever their length, so narration changes in
such scenes keep their keys; the pauses are stretched to the current length when the
sections are joined.

To record a section after cached ones, the earlier scenes still run, unrecorded and
quickly (replayed), so the shell, the files and the screen are as they would be.
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from narratty import __version__
from narratty.cache import Segment, SegmentCache, SegmentMeta
from narratty.errors import RenderError, UsageError
from narratty.render.pauses import SETTLE_MS, STILL_MS, Insert, shift_positions
from narratty.render.script import CARD, END_CUE, HEAD, SETUP, TAIL, HelperPlacement, Partial
from narratty.spec.model import ShowBrowser, Spec
from narratty.timeline import build_timeline

if TYPE_CHECKING:
    from narratty.build import Plan
    from narratty.render.timelapse import Layout

# Fixed stand-ins for the paths a tape names, so keys do not depend on them.
_OUTPUT = Path("/narratty/recording.mp4")
_EXIT_LOG = Path("/narratty/exits.log")
_PLACEMENT = HelperPlacement(diff_base="/narratty/diff-base")


class UnsafeReplay(RenderError):
    """A replayed scene still ran a command when its cut pause ended; it was marked
    to replay at its own pace, and the build has to record again."""

    def __init__(self, scenes: Sequence[str]) -> None:
        super().__init__(f"replaying {', '.join(scenes)} quickly left a command running")
        self.scenes = tuple(scenes)


# ── scene selection ──────────────────────────────────────────────────────────


def select_scenes(spec: Spec, ranges: Sequence[str]) -> list[str]:
    """Scene ids chosen by ``ranges``, in spec order.

    Each value is a comma-separated list of ``id``, ``from:to`` (inclusive), ``from:``
    (to the end) or ``:to`` (from the start).
    """
    ids = [scene.id for scene in spec.scenes]
    chosen: set[int] = set()
    for item in (part.strip() for value in ranges for part in value.split(",")):
        if not item:
            continue
        if ":" not in item:
            chosen.add(_index(ids, item))
            continue
        first, _, last = item.partition(":")
        low = _index(ids, first.strip()) if first.strip() else 0
        high = _index(ids, last.strip()) if last.strip() else len(ids) - 1
        if low > high:
            raise UsageError(
                f"scene range {item!r} runs backwards", hint=f"{ids[low]!r} comes after {ids[high]!r}."
            )
        chosen.update(range(low, high + 1))
    if not chosen:
        raise UsageError("--scenes selects no scene", hint=f"Scenes: {', '.join(ids)}")
    return [ids[index] for index in sorted(chosen)]


def _index(ids: list[str], name: str) -> int:
    if name in ids:
        return ids.index(name)
    close = difflib.get_close_matches(name, ids, n=1)
    hint = f"Did you mean {close[0]!r}?" if close else f"Scenes: {', '.join(ids)}"
    raise UsageError(f"unknown scene {name!r}", hint=hint)


def _visible(spec: Spec) -> list[str]:
    return [scene.id for scene in spec.scenes if not scene.hidden]


def needed(planned: Plan, selected: Sequence[str] | None = None) -> list[str]:
    """Labels of the sections the output shows: the selected visible scenes (default:
    all), with the lead-in and the tail when the selection starts or ends the video."""
    visible = _visible(planned.spec)
    scenes = visible if selected is None else [sid for sid in visible if sid in selected]
    if not scenes:
        raise UsageError("every selected scene is hidden, so there is nothing to show")
    timeline = planned.timeline
    starts, ends = scenes[0] == visible[0], scenes[-1] == visible[-1]
    return [
        *([HEAD] if timeline.lead_in_ms and starts else []),
        *scenes,
        *([TAIL] if timeline.tail_ms and ends else []),
        *([CARD] if timeline.end_card_ms and ends else []),
    ]


def select_plan(planned: Plan, selected: Sequence[str]) -> Plan:
    """``planned`` cut down to ``selected``: the timeline of a video of only those scenes."""
    keep = set(selected)
    visible = _visible(planned.spec)
    shown = [sid for sid in visible if sid in keep]
    spec = planned.spec
    starts, ends = shown[0] == visible[0], shown[-1] == visible[-1]
    timing = spec.timing.model_copy(
        update={
            "lead_in_ms": spec.timing.lead_in_ms if starts else 0,
            "tail_ms": spec.timing.tail_ms if ends else 0,
        }
    )
    end_card = spec.end_card if ends else spec.end_card.model_copy(update={"enabled": False})
    subset = spec.model_copy(
        update={"scenes": [s for s in spec.scenes if s.id in keep], "timing": timing, "end_card": end_card}
    )
    audio = {timing.scene_id: timing.audio_ms for timing in planned.timeline.scenes}
    return dataclasses.replace(
        planned,
        spec=subset,
        clips=tuple(clip for clip in planned.clips if clip.scene_id in keep),
        timeline=build_timeline(subset, audio),
    )


def runs_everything(spec: Spec) -> bool:
    """Whether the build needs the demo's effects on the workspace (artifacts, local
    pages shown in a browser view), so the scenes run even when all are cached."""
    if spec.workspace.artifacts:
        return True
    return any(
        isinstance(action, ShowBrowser) and not action.browser.url.startswith(("http://", "https://"))
        for scene in spec.scenes
        for action in scene.actions
    )


# ── keys ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Link:
    """One tape section in the key chain.

    ``content`` hashes only its own lines (it names the section across chains);
    ``pauses_ms`` are the planned lengths of its shortened pauses in this build.
    """

    label: str
    key: str
    content: str
    pauses_ms: tuple[int, ...] = ()


def _hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def inputs_digest(source: Path, patterns: Sequence[str]) -> str:
    """Hash of the files matching ``patterns`` under ``source`` (names and contents)."""
    digest = hashlib.sha256()
    files = sorted({path for pattern in patterns for path in source.glob(pattern) if path.is_file()})
    for path in files:
        digest.update(str(path.relative_to(source)).encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def base(planned: Plan, *, draft: bool) -> dict[str, Any]:
    """What every section's recording depends on beyond the tape."""
    from narratty.runtime import IN_CONTAINER_ENV

    spec = planned.spec
    return {
        "narratty": __version__,
        "container": bool(os.environ.get(IN_CONTAINER_ENV)),
        "draft": draft,
        "environment": spec.environment.model_dump(mode="json") if spec.environment else None,
        "workspace": spec.workspace.model_dump(mode="json", exclude={"artifacts"}),
        "sandbox": spec.sandbox.model_dump(mode="json"),
        "inputs": inputs_digest(planned.workspace_source, spec.cache.inputs) if spec.cache.inputs else None,
    }


def chain(planned: Plan, *, fast: bool, framerate: int) -> list[Link]:
    """Every section of the full tape with its key, in order."""
    from narratty.render.tape import build_tape

    tape = build_tape(
        planned.spec,
        planned.timeline,
        _OUTPUT,
        python="python",
        framerate=framerate,
        exit_log=_EXIT_LOG,
        placement=_PLACEMENT,
        fast=fast,
    )
    key = _hash(base(planned, draft=planned.draft))
    links = []
    for label, lines in tape.sections:
        key = _hash({"previous": key, "lines": lines})
        pauses = tuple(pause.planned_ms for pause in tape.pauses if pause.section == label)
        links.append(Link(label, key, _hash({"lines": lines}), pauses))
    return links


# ── what to record ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Job:
    """The sections taken from the cache, and how to record the others (None: nothing to record).

    ``recorded``: labels to record, in tape order.
    """

    cached: dict[str, Segment]
    partial: Partial | None
    recorded: tuple[str, ...] = ()


def schedule(
    planned: Plan,
    links: Sequence[Link],
    labels: Sequence[str],
    cache: SegmentCache,
    *,
    clean: bool = False,
    run_all: bool = False,
) -> Job:
    """Which of the needed ``labels`` come from the cache and which are recorded.

    ``clean`` ignores the cache. ``run_all``: the scenes must run even when all are
    cached, so the last needed section is recorded again.
    """
    keys = {link.label: link for link in links}
    cached: dict[str, Segment] = {}
    if not clean:
        cached = {label: hit for label in labels if (hit := cache.get(keys[label].key)) is not None}
    missing = [label for label in labels if label not in cached]
    if not missing and run_all:
        missing = [labels[-1]]
        cached.pop(labels[-1])
    if not missing:
        return Job(cached, None)
    realtime = frozenset(
        scene.id
        for scene in planned.spec.scenes
        if scene.replay == "realtime" or cache.realtime(keys[scene.id].content)
    )
    return Job(cached, Partial(frozenset(missing), missing[-1], realtime), tuple(missing))


def ran_spec(spec: Spec, partial: Partial) -> Spec:
    """``spec`` with only the scenes that ran in a recording of ``partial``."""
    if partial.last in (HEAD, TAIL, CARD):
        return spec if partial.last != HEAD else spec.model_copy(update={"scenes": []})
    ids = [scene.id for scene in spec.scenes]
    return spec.model_copy(update={"scenes": spec.scenes[: ids.index(partial.last) + 1]})


# ── joining ──────────────────────────────────────────────────────────────────


def owner(label: str) -> str | None:
    """The section a marker belongs to (None: one that marks a section's start)."""
    if label.startswith("end-"):
        return label.removeprefix("end-")
    if label.startswith("cue-overlay:"):
        return label.split(":")[1]
    return None


def positions_and_inserts(
    parts: Sequence[tuple[Link, SegmentMeta]], framerate: float
) -> tuple[dict[str, int], list[Insert]]:
    """Markers in the joined video, and the frames to repeat to fill its pauses."""
    positions: dict[str, int] = {}
    inserts: list[Insert] = []
    offset = 0
    for link, meta in parts:
        if link.label in (TAIL, CARD):
            positions.setdefault(f"cue-{END_CUE}", offset)
        if link.label == CARD:
            positions["card"] = offset
        elif link.label not in (HEAD, SETUP, TAIL):
            positions[f"scene-{link.label}"] = offset
        positions.update({label: offset + ms for label, ms in meta.marks_ms.items()})
        if len(meta.pauses_ms) != len(link.pauses_ms):
            raise RenderError(
                f"the cached recording of {link.label!r} does not match its tape", hint="Build with --clean."
            )
        for end, planned_ms in zip(meta.pauses_ms, link.pauses_ms, strict=True):
            frame = int((offset + end - STILL_MS / 2) * framerate / 1000)
            inserts.append(Insert(frame, round((planned_ms - SETTLE_MS) * framerate / 1000)))
        offset += meta.duration_ms
    positions.setdefault(f"cue-{END_CUE}", offset)
    return positions, inserts


def stitch(
    out: Plan,
    parts: Sequence[tuple[Link, Segment]],
    video: Path,
    work: Path,
    *,
    framerate: int,
) -> Layout:
    """Join the sections' recordings into ``video``, pauses filled, timelapses sped up."""
    from narratty.render import media, timelapse

    raw = work / "joined.mp4"
    media.concat([segment.video for _, segment in parts if segment.video is not None], raw)
    rate = media.probe(raw).frame_rate or framerate  # VHS writes 25 fps whatever its Framerate
    positions, inserts = positions_and_inserts([(link, segment.meta) for link, segment in parts], rate)
    filled = raw
    if any(insert.count > 0 for insert in inserts):
        filled = work / "filled.mp4"
        media.repeat_frames(raw, [(i.frame, i.count) for i in inserts], filled, fast=out.draft)
        positions = shift_positions(positions, inserts, rate)
    layout = timelapse.layout(out.timeline, positions)
    if layout.segments:
        timelapse.speed_up(filled, layout.segments, video, framerate=framerate)
    else:
        filled.replace(video)
    return layout


def pieces_meta(
    labels: Sequence[str],
    starts: Mapping[str, int],
    ends: Mapping[str, int],
    pause_ends: Sequence[tuple[str | None, int]],
    positions: Mapping[str, int],
) -> dict[str, SegmentMeta]:
    """Metadata of each recorded section, without its duration (known once cut)."""
    metas = {}
    for label in labels:
        start = starts[label]
        pauses = tuple(end - start for section, end in pause_ends if section == label)
        marks = {name: max(0, ms - start) for name, ms in positions.items() if owner(name) == label}
        metas[label] = SegmentMeta(ends[label] - start, pauses, marks)
    return metas
