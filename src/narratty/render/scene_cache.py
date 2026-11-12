"""Conservative keys for recordings whose scenes share shell state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
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
    previous = _digest({"format": 1, "settings": settings, "context": recording_context})
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
    """Hash the workspace files and Git revision before the recorded commands run."""
    root = workspace.resolve()
    excluded = {path.resolve() for path in exclude}
    digest = hashlib.sha256()
    git = shutil.which("git")
    if git:
        result = subprocess.run(
            [git, "rev-parse", "--verify", "HEAD"], cwd=root, capture_output=True, check=False
        )
        if result.returncode == 0:
            digest.update(result.stdout)
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


def recording_context(workspace: Path, *, exclude: frozenset[Path] = frozenset()) -> str:
    """Fingerprint the workspace, recorder code, tools and stable process environment."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"NARRATTY_REMOTE_EXIT_LOG", "NARRATTY_BRIDGE", "NARRATTY_WORKSPACE", IMAGE_ID_ENV}
    }
    return _digest(
        {
            "workspace": workspace_digest(workspace, exclude=exclude),
            "code": workspace_digest(Path(__file__).resolve().parents[1], ignore_bytecode=True),
            "tools": tool_fingerprint(),
            "python": sys.version,
            "environment": environment,
        }
    )


@dataclass(frozen=True)
class SceneRecording:
    """A recording and the positions of its scene boundaries."""

    video: Path
    starts_ms: dict[str, int]
    end_ms: int
    cut_ms: int


@dataclass(frozen=True)
class SceneCacheStats:
    """The number and size of stored scene recordings."""

    entries: int
    recordings: int
    bytes: int


class SceneCache:
    """Recordings referenced by cumulative scene keys."""

    def __init__(self, root: Path) -> None:
        self.root = root / "scenes"

    def get(self, key: str) -> SceneRecording | None:
        """Return a complete cache entry, or None for a missing or damaged entry."""
        try:
            data = json.loads((self.root / "keys" / f"{key}.json").read_text(encoding="utf-8"))
            name, starts, end, cut = data["video"], data["starts_ms"], data["end_ms"], data["cut_ms"]
            if not isinstance(name, str) or Path(name).name != name or not name.endswith(".mp4"):
                return None
            if not isinstance(starts, dict) or not all(
                isinstance(scene, str) and type(position) is int and position >= 0
                for scene, position in starts.items()
            ):
                return None
            if type(end) is not int or end < 0 or any(position > end for position in starts.values()):
                return None
            if type(cut) is not int or not 0 < cut <= end:
                return None
            video = self.root / "videos" / name
            if not video.is_file():
                return None
            (self.root / "keys" / f"{key}.json").touch()
            video.touch()
            return SceneRecording(video, starts, end, cut)
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def put(self, keys: dict[str, str], video: Path, starts_ms: dict[str, int], end_ms: int) -> None:
        """Atomically publish a recording after the build has passed its checks."""
        videos, entries = self.root / "videos", self.root / "keys"
        videos.mkdir(parents=True, exist_ok=True)
        entries.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.mp4"
        staged = videos / f"{name}.part"
        shutil.copyfile(video, staged)
        os.replace(staged, videos / name)
        scenes = list(keys)
        for index, (scene, key) in enumerate(keys.items()):
            cut = starts_ms[scenes[index + 1]] if index + 1 < len(scenes) else end_ms
            if cut <= starts_ms[scene]:
                continue
            data = json.dumps(
                {"video": name, "starts_ms": starts_ms, "end_ms": end_ms, "cut_ms": cut}, sort_keys=True
            )
            entry = entries / f"{key}.json"
            pending = entry.with_name(f"{entry.name}.{uuid.uuid4().hex}.part")
            pending.write_text(data, encoding="utf-8")
            os.replace(pending, entry)

    def stats(self) -> SceneCacheStats:
        entries = list((self.root / "keys").glob("*.json"))
        videos = list((self.root / "videos").glob("*.mp4"))
        return SceneCacheStats(len(entries), len(videos), sum(path.stat().st_size for path in videos))

    def prune(self, older_than_s: float, *, now: float | None = None) -> SceneCacheStats:
        """Remove stale entries and unreferenced recordings older than the cutoff."""
        cutoff = (time.time() if now is None else now) - older_than_s
        entries = list((self.root / "keys").glob("*.json"))
        removed = [entry for entry in entries if entry.stat().st_mtime < cutoff]
        for entry in removed:
            entry.unlink()
        referenced = set()
        for entry in entries:
            if entry in removed:
                continue
            try:
                referenced.add(json.loads(entry.read_text(encoding="utf-8"))["video"])
            except (OSError, ValueError, TypeError, KeyError):
                continue
        videos = [
            video
            for video in (self.root / "videos").glob("*.mp4")
            if video.name not in referenced and video.stat().st_mtime < cutoff
        ]
        size = sum(video.stat().st_size for video in videos)
        for video in videos:
            video.unlink()
        return SceneCacheStats(len(removed), len(videos), size)
