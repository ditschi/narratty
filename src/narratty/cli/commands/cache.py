"""``narratty cache``: inspect and prune the audio cache."""

from __future__ import annotations

import re

import typer

from narratty.errors import UsageError

cache_app = typer.Typer(help="Inspect or prune the audio and scene recording caches.", no_args_is_help=True)

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
    from narratty.cache import AudioCache, SegmentCache
    from narratty.paths import cache_dir
    from narratty.ui.console import out

    audio = AudioCache(cache_dir()).stats()
    scenes = SegmentCache(cache_dir()).stats()
    out.print(
        f"{audio.path}\n{audio.clips} clips, {_size(audio.bytes)}\n"
        f"{scenes.path}\n{scenes.clips} scene recordings, {_size(scenes.bytes)}",
        highlight=False,
        soft_wrap=True,
    )


@cache_app.command("prune")
def prune_command(
    older_than: str = typer.Option("30d", "--older-than", help="Remove entries unused for this long."),
    remove_all: bool = typer.Option(False, "--all", help="Remove every cached clip and scene recording."),
) -> None:
    """Remove cached clips and scene recordings that have not been used recently."""
    from narratty.cache import AudioCache, SegmentCache
    from narratty.paths import cache_dir
    from narratty.ui.console import out

    age = -1 if remove_all else parse_age(older_than)
    clips = AudioCache(cache_dir()).prune(age)
    scenes = SegmentCache(cache_dir()).prune(age)
    out.print(
        f"removed {clips.clips} clips, {_size(clips.bytes)}; "
        f"{scenes.clips} scene recordings, {_size(scenes.bytes)}",
        highlight=False,
    )
