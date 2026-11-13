"""``narratty cache``: inspect and prune audio or scene recordings."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import typer

from narratty.errors import UsageError

if TYPE_CHECKING:
    from narratty.render.scene_cache import SceneCacheStats

cache_app = typer.Typer(help="Inspect or prune the audio and scene caches.", no_args_is_help=True)

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_AGE = re.compile(r"^(\d+)([smhdw])$")


def parse_age(value: str) -> int:
    """``30d`` → seconds. Units: s, m, h, d, w."""
    match = _AGE.match(value.strip())
    if match is None:
        raise UsageError(f"invalid age {value!r}", hint="Use a number and a unit, e.g. 30d, 12h or 90m.")
    return int(match.group(1)) * _UNITS[match.group(2)]


def _size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")  # pragma: no cover


@cache_app.command("info")
def info_command() -> None:
    """Show where the caches are and how big they are."""
    from narratty.cache import AudioCache
    from narratty.paths import cache_dir
    from narratty.render.scene_cache import SceneCache
    from narratty.ui.console import out

    stats = AudioCache(cache_dir()).stats()
    out.print(f"{stats.path}\n{stats.clips} clips, {_size(stats.bytes)}", highlight=False, soft_wrap=True)
    scenes = SceneCache(cache_dir())
    scene_stats = scenes.stats()
    out.print(f"{scenes.root}\n{_scene_summary(scene_stats)}", highlight=False, soft_wrap=True)


def _scene_summary(stats: SceneCacheStats) -> str:
    partial = f", {stats.partial} interrupted writes" if stats.partial else ""
    return f"{stats.entries} scene entries, {stats.recordings} recordings{partial}, {_size(stats.bytes)}"


@cache_app.command("prune")
def prune_command(
    older_than: str = typer.Option("30d", "--older-than", help="Remove entries unused for this long."),
    remove_all: bool = typer.Option(False, "--all", help="Remove every entry in the selected cache."),
    scenes: bool = typer.Option(False, "--scenes", help="Prune scene recordings instead of audio clips."),
) -> None:
    """Remove cached clips or scene recordings that have not been used recently."""
    from narratty.cache import AudioCache
    from narratty.paths import cache_dir
    from narratty.render.scene_cache import SceneCache
    from narratty.ui.console import out

    age = -1 if remove_all else parse_age(older_than)
    if scenes:
        removed_scenes = SceneCache(cache_dir()).prune(age)
        out.print(f"removed {_scene_summary(removed_scenes)}", highlight=False)
        return
    removed = AudioCache(cache_dir()).prune(age)
    out.print(f"removed {removed.clips} clips, {_size(removed.bytes)}", highlight=False)
