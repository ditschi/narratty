"""Browser views: a web page or local HTML file shown over the terminal.

A ``browser`` action marks a point in its scene, like an overlay. Headless Chromium
(VHS records with it, so it is already there) captures the page at the video's width.
The view covers the picture under a slim address bar from there until its scene ends
or ``duration_ms`` has passed, and with ``scroll`` moves down the page meanwhile.

The mp4 gets the bar and the page as images for ffmpeg (see ``overlays.filter_graph``);
the cast page shows the same images over the player. Slides (:mod:`.slides`) are views
of a generated page, full screen without the bar.

Mermaid diagrams (``.mermaid`` elements) on a page that does not draw them itself are
drawn with a local ``mermaid.min.js`` before the capture, so they need no network.
"""

from __future__ import annotations

import base64
import contextlib
import glob
import json
import os
import select
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from narratty.errors import MissingDependencyError, RenderError
from narratty.render import slides
from narratty.render.overlays import FADE_MS, OverlayImage
from narratty.render.script import END_CUE, overlay_cue
from narratty.spec.model import Browser, ShowBrowser, ShowSlide, Slide, Spec, Terminal

CHROMIUM_NAMES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "chrome-headless-shell",
    "headless_shell",
)
# Where VHS (go-rod) downloads its own Chromium when none is installed.
ROD_BROWSERS = "~/.cache/rod/browser/*/chrome"
MAX_SCREENS = 4
SCROLL_PAUSE_MS = 1000
SETTLE_MS = 500
SLIDE_LOAD_MS = 5000
STARTUP_S = 90
PAGE_HEIGHT_JS = "Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight ?? 0)"
MERMAID_ENV = "NARRATTY_MERMAID_JS"
MERMAID_FILE = "mermaid.min.js"
FONTAWESOME_ENV = "NARRATTY_FONTAWESOME_JSON"
# Diagrams not drawn yet, on a page that does not bring its own Mermaid.
NEEDS_MERMAID_JS = (
    "typeof window.mermaid === 'undefined' && [...document.querySelectorAll('.mermaid')]"
    ".some(e => !e.shadowRoot && !e.querySelector('svg') && !e.dataset.processed)"
)
NEEDS_FONTAWESOME = (
    "[...document.querySelectorAll('.mermaid')].some(e => /\\bfa:[\\w-]+/.test(e.textContent))"
)
RUN_MERMAID_JS = (
    "mermaid.initialize({startOnLoad: false, theme: document.body.dataset.mermaidTheme || 'default', "
    "fontFamily: 'DejaVu Sans, Noto Color Emoji, sans-serif'});"
    "mermaid.run({querySelector: '.mermaid'})"
    ".then(() => {"
    "const focus = document.body.dataset.mermaidFocus;"
    "if (!focus) return;"
    "const targets = [...document.querySelectorAll('.node[id], .cluster[id]')];"
    "const target = targets.find(e => e.id === focus || "
    "e.id.endsWith('-' + focus + '-0') || e.id.endsWith('-' + focus));"
    "if (!target) throw new Error('no Mermaid node or subgraph with id ' + focus);"
    "target.classList.add('narratty-focus');"
    "})"
    ".catch(e => { throw new Error((e && (e.message || e.str)) || String(e)); })"
)


@dataclass(frozen=True)
class View:
    """One browser view or slide (then ``browser`` is None) as it appears in the output."""

    browser: Browser | None
    start_ms: int
    end_ms: int
    scene_id: str = ""
    slide: Slide | None = None


def schedule(spec: Spec, times: Mapping[str, int]) -> list[View]:
    """Every browser view and slide of ``spec`` with its start and end, given scene and cue ``times``.

    A later view in the same scene replaces an earlier one.
    """
    end = times[END_CUE]
    visible = [scene for scene in spec.scenes if not scene.hidden]
    views: list[View] = []
    for number, scene in enumerate(visible):
        scene_end = times[visible[number + 1].id] if number + 1 < len(visible) else end
        for index, action in enumerate(scene.actions):
            if isinstance(action, ShowBrowser):
                view = View(action.browser, 0, 0, scene.id)
                duration = action.browser.duration_ms
            elif isinstance(action, ShowSlide):
                view = View(None, 0, 0, scene.id, action.slide)
                duration = action.slide.duration_ms
            else:
                continue
            start = times[overlay_cue(scene.id, index)]
            stop = scene_end if duration is None else min(scene_end, start + duration)
            if views and views[-1].end_ms > start:
                views[-1] = replace(views[-1], end_ms=start)
            views.append(replace(view, start_ms=start, end_ms=stop))
    return [view for view in views if view.end_ms > view.start_ms]


def scaled(views: Sequence[View], factor: float) -> list[View]:
    """``views`` with every time multiplied by ``factor`` (planned → rendered length)."""
    return [replace(v, start_ms=round(v.start_ms * factor), end_ms=round(v.end_ms * factor)) for v in views]


# ── capture ───────────────────────────────────────────────────────────────────


def find_chromium() -> str:
    """Path of a Chromium (or Chrome) binary."""
    for name in CHROMIUM_NAMES:
        found = shutil.which(name)
        if found:
            return found
    downloaded = sorted(glob.glob(os.path.expanduser(ROD_BROWSERS)))
    if downloaded:
        return downloaded[-1]
    raise MissingDependencyError(
        "browser views need Chromium or Chrome",
        hint="install chromium, or render in the narratty image (--runtime docker)",
    )


def find_mermaid() -> Path:
    """Path of ``mermaid.min.js``: ``NARRATTY_MERMAID_JS``, else the one in the data directory."""
    from narratty.paths import data_dir

    path = Path(os.environ.get(MERMAID_ENV) or data_dir() / MERMAID_FILE)
    if path.is_file():
        return path
    raise MissingDependencyError(
        f"Mermaid diagrams need {MERMAID_FILE}, which is not at {path}",
        hint=f"render in the narratty image (--runtime docker), or put {MERMAID_FILE} "
        f"from the mermaid npm package at {path} or name its path in {MERMAID_ENV}",
    )


def page_url(url: str, workspace: Path) -> str:
    """``url`` as Chromium loads it: web and data URLs as they are, files from the workspace."""
    if url.startswith(("http://", "https://", "file://", "data:")):
        return url
    path = (workspace / url).resolve()
    if not path.is_file():
        raise RenderError(f"browser: {url} is not a file in the workspace")
    return path.as_uri()


def check_network(spec: Spec, url: str) -> None:
    """A web page cannot load in the container without network access."""
    if (
        url.startswith(("http://", "https://"))
        and os.environ.get("NARRATTY_IN_CONTAINER")
        and spec.sandbox.network == "none"
    ):
        raise RenderError(
            f"browser: {url} needs network access",
            hint="set 'sandbox: {network: full}' in the spec, or show a local HTML file",
        )


class _DevTools:
    """Chromium's DevTools protocol over ``--remote-debugging-pipe`` (fds 3 and 4)."""

    def __init__(self, process: subprocess.Popen[bytes], send_fd: int, receive_fd: int) -> None:
        self.process, self._send, self._receive = process, send_fd, receive_fd
        self._buffer, self._next_id = b"", 0
        self.events: list[dict[str, Any]] = []

    def _message(self, deadline: float) -> dict[str, Any]:
        while b"\0" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self._receive], [], [], remaining)[0]:
                raise TimeoutError
            chunk = os.read(self._receive, 1 << 16)
            if not chunk:
                raise RenderError("browser: Chromium exited unexpectedly")
            self._buffer += chunk
        raw, _, self._buffer = self._buffer.partition(b"\0")
        message: dict[str, Any] = json.loads(raw)
        return message

    def call(self, method: str, session: str | None = None, timeout_s: float = 30, **params: Any) -> Any:
        """Send one command and wait for its result; events meanwhile are kept."""
        self._next_id += 1
        command: dict[str, Any] = {"id": self._next_id, "method": method, "params": params}
        if session:
            command["sessionId"] = session
        os.write(self._send, json.dumps(command).encode() + b"\0")
        deadline = time.monotonic() + timeout_s
        while True:
            message = self._message(deadline)
            if message.get("id") == self._next_id:
                if "error" in message:
                    raise RenderError(f"browser: {method} failed: {message['error'].get('message')}")
                return message.get("result", {})
            self.events.append(message)

    def wait_for(self, method: str, timeout_s: float) -> bool:
        """Wait until the event ``method`` arrives; False after ``timeout_s``."""
        deadline = time.monotonic() + timeout_s
        while not any(event.get("method") == method for event in self.events):
            try:
                self.events.append(self._message(deadline))
            except TimeoutError:
                return False
        return True


def _pipe_fds(commands: int, replies: int) -> None:
    """In the child: put the pipe ends where Chromium expects them (fds 3 and 4)."""
    commands, replies = os.dup(commands), os.dup(replies)
    os.dup2(commands, 3)
    os.dup2(replies, 4)


def capture(
    url: str, width: int, view_px: int, scroll: str | int, load_ms: int, path: Path, *, chromium: str
) -> int:
    """Screenshot ``url`` in a ``width`` × ``view_px`` viewport into ``path`` (PNG).

    The image is taller than the viewport by the distance to scroll: with ``auto`` the
    rest of the page, at most ``MAX_SCREENS`` screens in all. Returns that distance.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    to_chromium, chromium_in = os.pipe()
    chromium_out, from_chromium = os.pipe()
    # Chromium's helper processes may still write to the profile while it is removed.
    with tempfile.TemporaryDirectory(prefix="narratty-chromium-", ignore_cleanup_errors=True) as profile:
        argv = [
            chromium,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--remote-debugging-pipe",
            f"--user-data-dir={profile}",
        ]
        if os.environ.get("VHS_NO_SANDBOX") or os.geteuid() == 0:
            argv.append("--no-sandbox")
        # Chromium reads commands from fd 3 and writes replies to fd 4.
        process = subprocess.Popen(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,  # chatty; an undrained pipe would block it
            pass_fds=(3, 4),
            preexec_fn=lambda: _pipe_fds(to_chromium, from_chromium),  # noqa: PLW1509
            start_new_session=True,  # so its helper processes can be stopped with it
        )
        os.close(to_chromium)
        os.close(from_chromium)
        tools = _DevTools(process, chromium_in, chromium_out)
        try:
            # The first start of a fresh profile can take a while on slow machines.
            target = tools.call("Target.createTarget", timeout_s=STARTUP_S, url="about:blank")["targetId"]
            session = tools.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
            tools.call(
                "Emulation.setDeviceMetricsOverride",
                session,
                width=width,
                height=view_px,
                deviceScaleFactor=1,
                mobile=False,
            )
            tools.call("Page.enable", session)
            navigation = tools.call("Page.navigate", session, url=url)
            if navigation.get("errorText"):
                raise RenderError(f"browser: could not load {url}: {navigation['errorText']}")
            tools.wait_for("Page.loadEventFired", load_ms / 1000)
            time.sleep(SETTLE_MS / 1000)  # web fonts, late layout
            if _evaluate(tools, session, NEEDS_MERMAID_JS):
                _evaluate(tools, session, find_mermaid().read_text(encoding="utf-8"), timeout_s=60)
                try:
                    if _evaluate(tools, session, NEEDS_FONTAWESOME):
                        _register_fontawesome(tools, session)
                    _evaluate(tools, session, RUN_MERMAID_JS, timeout_s=60, await_promise=True)
                except RenderError as error:
                    raise RenderError(f"browser: Mermaid cannot draw a diagram: {error.message}") from error
            page_px = _evaluate(tools, session, PAGE_HEIGHT_JS)
            if page_px is None:
                page_px = view_px
            if scroll == "auto":
                distance = max(0, min(int(page_px), view_px * MAX_SCREENS) - view_px)
            else:
                distance = 0 if scroll == "none" else int(scroll)
            shot = tools.call(
                "Page.captureScreenshot",
                session,
                timeout_s=60,
                format="png",
                captureBeyondViewport=True,
                clip={"x": 0, "y": 0, "width": width, "height": view_px + distance, "scale": 1},
            )
            path.write_bytes(base64.b64decode(shot["data"]))
            with contextlib.suppress(RenderError, TimeoutError, OSError):
                tools.call("Browser.close", timeout_s=5)
        except TimeoutError as error:
            raise RenderError(f"browser: Chromium did not answer while capturing {url}") from error
        finally:
            os.close(chromium_in)
            os.close(chromium_out)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    return distance


def _evaluate(
    tools: _DevTools, session: str, expression: str, *, timeout_s: float = 30, await_promise: bool = False
) -> Any:
    """The value of ``expression`` in the page; a thrown error becomes a :class:`RenderError`."""
    reply = tools.call(
        "Runtime.evaluate",
        session,
        timeout_s=timeout_s,
        expression=expression,
        returnByValue=True,
        awaitPromise=await_promise,
    )
    if details := reply.get("exceptionDetails"):
        exception = details.get("exception") or {}
        message = exception.get("description") or exception.get("value") or details.get("text", "")
        lines = [line for line in str(message).splitlines() if not line.startswith("    at ")]
        raise RenderError("\n".join(lines).removeprefix("Error: ").strip())
    return reply["result"].get("value")


def _register_fontawesome(tools: _DevTools, session: str) -> None:
    """Register the bundled Iconify Font Awesome pack before Mermaid draws a diagram."""
    path = os.environ.get(FONTAWESOME_ENV)
    if not path:
        raise MissingDependencyError(
            "Mermaid Font Awesome icons need the fa6-solid Iconify pack",
            hint=f"set {FONTAWESOME_ENV} to its icons.json file or render in the narratty image",
        )
    try:
        icons = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RenderError(f"browser: cannot load the Font Awesome icon pack at {path}: {error}") from error
    pack = json.dumps({"name": "fa", "icons": icons}, separators=(",", ":"))
    _evaluate(tools, session, f"mermaid.registerIconPacks([{pack}]);", timeout_s=60)


# ── drawing ───────────────────────────────────────────────────────────────────


def bar_height(terminal: Terminal) -> int:
    """Height of the address bar above the page."""
    return round(terminal.font_size * 1.8)


def draw_bar(url: str, width: int, height: int, path: Path) -> Path:
    """A minimal browser title bar: three window dots and the address."""
    from PIL import Image, ImageDraw

    from narratty.render.overlays import _font

    image = Image.new("RGBA", (width, height), (40, 42, 54, 255))
    canvas = ImageDraw.Draw(image)
    dot = max(4, height // 6)
    for number, color in enumerate(((255, 85, 85), (241, 250, 140), (80, 250, 123))):
        x = height // 2 + number * dot * 3
        canvas.ellipse((x - dot, height // 2 - dot, x + dot, height // 2 + dot), fill=color)
    left = height // 2 + 9 * dot
    pad = height // 6
    canvas.rounded_rectangle(
        (left, pad, width - height // 2, height - pad), radius=(height - 2 * pad) // 2, fill=(68, 71, 90)
    )
    font = _font(False, round(height * 0.45))
    address = url.removeprefix("https://").removeprefix("http://")
    canvas.text((left + height // 2, height // 2), address, font=font, fill=(248, 248, 242), anchor="lm")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


@dataclass(frozen=True)
class Shot:
    """A captured view: the bar (none for a slide), the page and how far it scrolls."""

    view: View
    bar: Path | None
    page: Path
    view_px: int
    scroll_px: int

    @property
    def scroll_ms(self) -> tuple[int, int]:
        """When scrolling starts and ends: a pause at the top and at the bottom."""
        pause = min(SCROLL_PAUSE_MS, (self.view.end_ms - self.view.start_ms) // 4)
        return self.view.start_ms + pause, self.view.end_ms - pause


def shoot(spec: Spec, views: Sequence[View], workspace: Path, directory: Path) -> list[Shot]:
    """Capture each view's page and draw its bar into ``directory``."""
    if not views:
        return []
    chromium = find_chromium()
    shots = []
    for number, view in enumerate(views):
        try:
            shots.append(_shoot(spec, view, workspace, directory, number, chromium))
        except RenderError as error:
            if not view.scene_id:
                raise
            raise RenderError(f"scene {view.scene_id}: {error.message}", hint=error.hint) from error
    return shots


def _shoot(spec: Spec, view: View, workspace: Path, directory: Path, number: int, chromium: str) -> Shot:
    width, height = spec.terminal.width, spec.terminal.height
    page = directory / f"browser-{number}.png"
    if view.slide is not None:
        if view.slide.html is not None:
            url = page_url(view.slide.html, workspace)
        else:
            html_file = directory / f"slide-{number}.html"
            html_file.parent.mkdir(parents=True, exist_ok=True)
            html_file.write_text(slides.page(view.slide, spec.slides.theme, workspace), encoding="utf-8")
            url = html_file.as_uri()
        capture(url, width, height, "none", SLIDE_LOAD_MS, page, chromium=chromium)
        return Shot(view, None, page, height, 0)
    browser = view.browser
    assert browser is not None
    bar_px = bar_height(spec.terminal)
    url = page_url(browser.url, workspace)
    check_network(spec, url)
    scroll_px = capture(url, width, height - bar_px, browser.scroll, browser.load_ms, page, chromium=chromium)
    bar = draw_bar(browser.address or browser.url, width, bar_px, directory / f"browser-{number}-bar.png")
    return Shot(view, bar, page, height - bar_px, scroll_px)


def images(shots: Sequence[Shot], bar_px: int) -> list[OverlayImage]:
    """Each shot as images for ffmpeg: the page (scrolling) and the bar above it."""
    result = []
    for shot in shots:
        start, end = shot.view.start_ms, shot.view.end_ms
        top = str(bar_px) if shot.bar else "0"
        result.append(
            OverlayImage(shot.page, "0", top, start, end, shot.view_px, shot.scroll_px, shot.scroll_ms)
        )
        if shot.bar:
            result.append(OverlayImage(shot.bar, "0", "0", start, end))
    return result


def page_views(shots: Sequence[Shot], terminal: Terminal) -> list[dict[str, Any]]:
    """The views as data for the cast page (times in seconds, sizes in percent of the width)."""

    def data_url(path: Path) -> str:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    width = terminal.width
    return [
        {
            "start": shot.view.start_ms / 1000,
            "end": shot.view.end_ms / 1000,
            "scroll": [shot.scroll_ms[0] / 1000, shot.scroll_ms[1] / 1000],
            "bar": data_url(shot.bar) if shot.bar else None,
            "page": data_url(shot.page),
            "bar_height": round(100 * bar_height(terminal) / width, 3) if shot.bar else 0,
            "view_height": round(100 * shot.view_px / width, 3),
            "scroll_by": round(100 * shot.scroll_px / width, 3),
            "fade": FADE_MS / 1000,
        }
        for shot in shots
    ]
