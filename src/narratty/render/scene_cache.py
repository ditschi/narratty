"""Conservative keys for recordings whose scenes share shell state."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from narratty.spec.model import Spec
from narratty.timeline import Timeline


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def scene_keys(spec: Spec, timeline: Timeline, recording_context: str) -> dict[str, str]:
    """Hash each scene and its entire preceding state, including recording context."""
    settings = spec.model_dump(mode="json", exclude={"scenes", "tts", "subtitles"})
    previous = _digest({"format": 2, "settings": settings, "context": recording_context})
    keys: dict[str, str] = {}
    for scene in spec.scenes:
        timing = asdict(timeline.scene(scene.id))
        timing.pop("start_ms")
        previous = _digest(
            {
                "previous": previous,
                "scene": scene.model_dump(mode="json", exclude={"narration"}),
                "timing": timing,
            }
        )
        keys[scene.id] = previous
    return keys


def workspace_digest(
    workspace: Path, *, exclude: frozenset[Path] = frozenset(), ignore_bytecode: bool = False
) -> str:
    """Hash the workspace files before the recorded commands run.

    Only the files count, not the Git history: a commit that changes no file keeps the key.
    """
    root = workspace.resolve()
    excluded = {path.resolve() for path in exclude}
    digest = hashlib.sha256()
    for directory, folders, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        folders[:] = sorted(
            folder
            for folder in folders
            if folder != ".git"
            and not (ignore_bytecode and folder == "__pycache__")
            and (parent / folder).resolve() not in excluded
        )
        for name in sorted([*folders, *files]):
            path = parent / name
            if path.resolve() in excluded:
                continue
            info = path.lstat()
            digest.update(os.fsencode(str(path.relative_to(root))) + b"\0")
            digest.update(str(info.st_mode).encode() + b"\0")
            if stat.S_ISLNK(info.st_mode):
                digest.update(os.fsencode(os.readlink(path)))
            elif stat.S_ISREG(info.st_mode):
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


# Where the narratty image records the ID it was given at build time (see the Dockerfile).
IMAGE_ID_FILE = Path("/opt/narratty/image-id")
IMAGE_ID_ENV = "NARRATTY_IMAGE_ID"
_TOOLS = ("vhs", "ttyd", "ffmpeg", "ffprobe", "bash", "zsh", "fish", "tmux")
# Where VHS's browser launcher (go-rod) looks for a browser on Linux and macOS.
_BROWSERS = (
    "chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "/opt/google/chrome/chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def _file_identity(executable: str) -> tuple[str, int, int] | None:
    """The resolved file behind ``executable``, with its size and modification time."""
    try:
        real = Path(executable).resolve()
        if real.name == "snap" and Path(executable).parent == Path("/snap/bin"):
            # Snap commands all link to /usr/bin/snap; the revision is in the package's path.
            real = Path("/snap", Path(executable).name, "current").resolve()
        info = real.stat()
    except OSError:
        return None
    return str(real), info.st_size, info.st_mtime_ns


def _output(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout + result.stderr


def tool_fingerprint() -> dict[str, Any]:
    """The recorder's tools, browser, fonts and image, as far as they change the footage."""
    tools = {}
    for name in (*_TOOLS, *_BROWSERS):
        executable = shutil.which(name)
        if executable and (identity := _file_identity(executable)):
            tools[name] = identity
    rod = Path.home() / ".cache" / "rod" / "browser"
    try:
        downloaded = sorted(path.name for path in rod.iterdir())
    except OSError:
        downloaded = []
    vhs, fc_list = shutil.which("vhs"), shutil.which("fc-list")
    fonts = sorted(_output([fc_list]).splitlines()) if fc_list else []
    try:
        image_file = IMAGE_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        image_file = ""
    return {
        "tools": tools,
        "rod_browsers": downloaded,
        "vhs_version": _output([vhs, "--version"]).strip() if vhs else "",
        "fonts": _digest(fonts),
        "image": [os.environ.get(IMAGE_ID_ENV, ""), image_file],
    }


# Variables that change how the recorded shell and its programs draw. The spec's own
# ``sandbox.env`` is part of the scene keys already; its ``env_passthrough`` names are added.
_ENVIRONMENT = frozenset({"TERM", "COLORTERM", "LANG", "LANGUAGE", "TZ", "SHELL", "PATH", "HOME", "NO_COLOR"})


def recording_context(
    workspace: Path, *, exclude: frozenset[Path] = frozenset(), passthrough: Iterable[str] = ()
) -> str:
    """Fingerprint the workspace, recorder code, tools and the environment that shapes output.

    The recorder code is narratty's own files (not its version, which a development
    install derives from the Git revision).
    """
    names = _ENVIRONMENT | set(passthrough)
    environment = {key: value for key, value in os.environ.items() if key in names or key.startswith("LC_")}
    return _digest(
        {
            "workspace": workspace_digest(workspace, exclude=exclude),
            "code": workspace_digest(Path(__file__).resolve().parents[1], ignore_bytecode=True),
            "tools": tool_fingerprint(),
            "python": sys.version,
            "environment": environment,
        }
    )


# Storage. A build that reuses cached scenes joins their footage to a fresh recording,
# re-encoding both. Storing that joined video would re-encode the oldest scenes again on
# every later reuse (generational loss, and frame rounding that adds up). So the cache
# never stores a join: it stores each fresh recording as VHS wrote it, and an entry lists
# the parts of stored recordings that make up its scenes. Entries of reused scenes stay
# as they are; only freshly recorded scenes get new entries, whose parts are the reused
# prefix's parts plus the new recording. Every build re-encodes each frame once, from
# VHS's own output.


@dataclass(frozen=True)
class Footage:
    """The part of a stored recording between two positions of its own."""

    video: Path
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class SceneRecording:
    """The footage of a scene prefix and where its scenes start once the parts are joined."""

    parts: tuple[Footage, ...]
    starts_ms: dict[str, int]
    cut_ms: int


@dataclass(frozen=True)
class SceneCacheStats:
    """The number and size of stored scene recordings."""

    entries: int
    recordings: int
    bytes: int
    partial: int = 0  # files left by interrupted writes; their size counts in ``bytes``


_PARTIAL_GRACE_S = 3600


def _position(value: Any) -> bool:
    return type(value) is int and value >= 0


class SceneCache:
    """Recordings referenced by cumulative scene keys."""

    def __init__(self, root: Path) -> None:
        self.root = root / "scenes"

    def _entry(self, key: str) -> Path:
        return self.root / "keys" / f"{key}.json"

    def has(self, key: str) -> bool:
        """Whether an entry exists for ``key``, usable or not."""
        return self._entry(key).is_file()

    def get(self, key: str) -> SceneRecording | None:
        """Return a complete cache entry, or None for a missing or damaged entry."""
        try:
            data = json.loads(self._entry(key).read_text(encoding="utf-8"))
            parts, starts, cut = data["parts"], data["starts_ms"], data["cut_ms"]
            if not isinstance(parts, list) or not parts:
                return None
            footage = []
            for part in parts:
                name, begin, end = part["video"], part["start_ms"], part["end_ms"]
                if not isinstance(name, str) or Path(name).name != name or not name.endswith(".mp4"):
                    return None
                if not (_position(begin) and _position(end) and begin < end):
                    return None
                footage.append(Footage(self.root / "videos" / name, begin, end))
            if not isinstance(starts, dict) or not all(
                isinstance(scene, str) and _position(position) for scene, position in starts.items()
            ):
                return None
            if not _position(cut) or cut == 0 or any(position >= cut for position in starts.values()):
                return None
            if not all(part.video.is_file() for part in footage):
                return None
        except (OSError, ValueError, TypeError, KeyError):
            return None
        # Marks the entry as used for `cache prune`; a read-only cache is still usable.
        for used in (self._entry(key), *(part.video for part in footage)):
            with contextlib.suppress(OSError):
                used.touch()
        return SceneRecording(tuple(footage), starts, cut)

    def put(
        self,
        keys: dict[str, str],
        video: Path,
        starts_ms: dict[str, int],
        end_ms: int,
        *,
        base: SceneRecording | None = None,
        video_starts_ms: dict[str, int] | None = None,
        video_end_ms: int | None = None,
    ) -> None:
        """Atomically publish a recording after the build has passed its checks.

        ``keys`` are the visible scenes in order and ``starts_ms``/``end_ms`` their
        positions in the build's video. Without ``base`` that video is ``video``. With
        it, the first scenes were reused from ``base`` and keep their entries; ``video``
        is the fresh recording of the rest, and ``video_starts_ms``/``video_end_ms`` are
        positions in it.
        """
        reused = set(base.starts_ms) if base else set()
        fresh = [scene for scene in keys if scene not in reused]
        if not fresh:
            return
        own_starts = starts_ms if video_starts_ms is None else video_starts_ms
        own_end = end_ms if video_end_ms is None else video_end_ms
        videos, entries = self.root / "videos", self.root / "keys"
        videos.mkdir(parents=True, exist_ok=True)
        entries.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.mp4"
        staged = videos / f"{name}.part"
        try:
            shutil.copyfile(video, staged)
            os.replace(staged, videos / name)
        finally:
            staged.unlink(missing_ok=True)
        prefix = [asdict(part) | {"video": part.video.name} for part in base.parts] if base else []
        first = own_starts[fresh[0]] if base else 0
        scenes = list(keys)
        for index, scene in enumerate(scenes):
            if scene in reused:
                continue
            following = scenes[index + 1] if index + 1 < len(scenes) else None
            cut = starts_ms[following] if following else end_ms
            own_cut = own_starts[following] if following else own_end
            if cut <= starts_ms[scene] or own_cut <= first:
                continue
            data = json.dumps(
                {
                    "parts": [*prefix, {"video": name, "start_ms": first, "end_ms": own_cut}],
                    "starts_ms": {other: starts_ms[other] for other in scenes[: index + 1]},
                    "cut_ms": cut,
                },
                sort_keys=True,
            )
            entry = entries / f"{keys[scene]}.json"
            pending = entry.with_name(f"{entry.name}.{uuid.uuid4().hex}.part")
            try:
                pending.write_text(data, encoding="utf-8")
                os.replace(pending, entry)
            finally:
                pending.unlink(missing_ok=True)

    def _partial(self) -> list[Path]:
        return [*(self.root / "videos").glob("*.part"), *(self.root / "keys").glob("*.part")]

    def stats(self) -> SceneCacheStats:
        entries = list((self.root / "keys").glob("*.json"))
        files = [*(self.root / "videos").glob("*.mp4"), *(partial := self._partial())]
        return SceneCacheStats(
            len(entries), len(files) - len(partial), sum(_size(path) for path in files), len(partial)
        )

    def prune(self, older_than_s: float, *, now: float | None = None) -> SceneCacheStats:
        """Remove stale entries, unreferenced recordings and leftovers of interrupted writes.

        Leftovers younger than an hour may belong to a running build and are kept.
        """
        now = time.time() if now is None else now
        cutoff = now - older_than_s
        entries = list((self.root / "keys").glob("*.json"))
        removed = [entry for entry in entries if entry.stat().st_mtime < cutoff]
        for entry in removed:
            entry.unlink()
        referenced: set[str] = set()
        for entry in entries:
            if entry in removed:
                continue
            try:
                parts = json.loads(entry.read_text(encoding="utf-8"))["parts"]
                referenced.update(part["video"] for part in parts)
            except (OSError, ValueError, TypeError, KeyError):
                continue
        videos = [
            video
            for video in (self.root / "videos").glob("*.mp4")
            if video.name not in referenced and video.stat().st_mtime < cutoff
        ]
        partial_cutoff = min(cutoff, now - _PARTIAL_GRACE_S)
        partial = [path for path in self._partial() if path.stat().st_mtime < partial_cutoff]
        size = sum(_size(path) for path in [*videos, *partial])
        for path in [*videos, *partial]:
            path.unlink(missing_ok=True)
        return SceneCacheStats(len(removed), len(videos), size, len(partial))


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:  # removed by a concurrent build
        return 0
