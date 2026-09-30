"""The closing card: "Created with narratty", a link to the docs and a QR code of it.

It is on by default. ``end_card: false`` in the spec, ``--no-end-card`` or
``[end_card] enabled = false`` in config.toml turn it off (in that order of precedence:
flag, spec, config).

The card is drawn by the terminal itself: the tape runs
``python -m narratty.end_card`` while recording is hidden, and this module centers
the text and QR code in whatever size the terminal turned out to be.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from narratty.config import config_file, config_section
from narratty.errors import UsageError
from narratty.spec.model import Spec

DOCS_URL = "https://ditschi.github.io/narratty/"
CREDIT = "Created with narratty"

_DARK, _LIGHT = (0, 0, 0), (255, 255, 255)
_BOLD, _RESET, _HIDE_CURSOR = "\x1b[1m", "\x1b[0m", "\x1b[?25l"
_GAP = 4  # columns between the QR code and the text beside it


def default_enabled(directory: Path | None = None) -> bool:
    """``[end_card] enabled`` from config.toml (True when unset)."""
    value = config_section("end_card", directory).get("enabled", True)
    if not isinstance(value, bool):
        raise UsageError(f"{config_file(directory)}: [end_card] enabled must be true or false")
    return value


def is_enabled(spec: Spec, flag: bool | None = None, directory: Path | None = None) -> bool:
    """Whether the card is shown: the flag wins, then the spec, then the user's config."""
    if flag is not None:
        return flag
    if spec.end_card.enabled is not None:
        return spec.end_card.enabled
    return default_enabled(directory)


def with_end_card(spec: Spec, flag: bool | None = None) -> Spec:
    """``spec`` with ``end_card.enabled`` resolved to True or False."""
    enabled = is_enabled(spec, flag)
    return spec.model_copy(update={"end_card": spec.end_card.model_copy(update={"enabled": enabled})})


def container_flag(spec_path: Path, flag: bool | None) -> str:
    """The resolved choice as a flag for the command re-run inside the container.

    The user's config.toml is not mounted there, so the host decides.
    """
    from narratty.spec import load_spec

    return "--end-card" if is_enabled(load_spec(spec_path), flag) else "--no-end-card"


# ── drawing ───────────────────────────────────────────────────────────────────


def _cell(top: bool, bottom: bool) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    return (_DARK if top else _LIGHT), (_DARK if bottom else _LIGHT)


def qr_lines(url: str, border: int = 2) -> list[str]:
    """The QR code of ``url`` as terminal lines, two modules per character cell.

    Colors are explicit 24-bit black and white, so the code scans on any theme.
    """
    import segno

    code = segno.make(url, error="m")
    matrix = [[bool(module) for module in row] for row in code.matrix_iter(border=border)]
    if len(matrix) % 2:
        matrix.append([False] * len(matrix[0]))
    lines: list[str] = []
    for top, bottom in zip(matrix[::2], matrix[1::2], strict=True):
        line, current = [], None
        for colors in (_cell(t, b) for t, b in zip(top, bottom, strict=True)):
            if colors != current:
                (fr, fg, fb), (br, bg, bb) = colors
                line.append(f"\x1b[38;2;{fr};{fg};{fb};48;2;{br};{bg};{bb}m")
                current = colors
            line.append("▀")
        lines.append("".join(line) + _RESET)
    return lines


def qr_size(url: str, border: int = 2) -> tuple[int, int]:
    """Columns and rows the QR code of ``url`` takes."""
    import segno

    side = int(segno.make(url, error="m").symbol_size(border=border)[0])
    return side, (side + 1) // 2


def _center(block: Sequence[tuple[str, int]], cols: int, rows: int) -> str:
    """Center lines (text, visible width) on a ``cols`` x ``rows`` screen."""
    width = max(visible for _, visible in block)
    left = " " * max(0, (cols - width) // 2)
    top = max(0, (rows - len(block)) // 2)
    return "\n" * top + "\n".join(left + text for text, _ in block)


def compose(cols: int, rows: int, url: str = DOCS_URL, *, qr: bool = True) -> str:
    """The card for a ``cols`` x ``rows`` terminal.

    The QR code goes beside the text when there is room, else above it, else it is
    left out.
    """
    text = [(f"{_BOLD}{CREDIT}{_RESET}", len(CREDIT)), ("", 0), (url, len(url))]
    text_width = max(visible for _, visible in text)
    if qr:
        qr_width, qr_height = qr_size(url)
        code = [(line, qr_width) for line in qr_lines(url)]
        if qr_width + _GAP + text_width <= cols and qr_height <= rows:
            offset = (qr_height - len(text)) // 2
            side = [("", 0)] * offset + text + [("", 0)] * (qr_height - len(text) - offset)
            pad = " " * _GAP
            return _center(
                [(q + pad + t, qr_width + _GAP + w) for (q, _), (t, w) in zip(code, side, strict=True)],
                cols,
                rows,
            )
        if max(qr_width, text_width) <= cols and qr_height + 1 + len(text) <= rows:
            return _center([*code, ("", 0), *text], cols, rows)
    return _center(text, cols, rows)


def main(argv: Iterable[str] | None = None) -> None:
    """Draw the card in the current terminal (run by the tape)."""
    parser = argparse.ArgumentParser(prog="python -m narratty.end_card", description=__doc__)
    parser.add_argument("url", nargs="?", default=DOCS_URL)
    parser.add_argument("--no-qr", dest="qr", action="store_false", help="Leave out the QR code.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    size = shutil.get_terminal_size()
    sys.stdout.write(compose(size.columns, size.lines, args.url, qr=args.qr) + _HIDE_CURSOR)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
