"""Browser views: a web page or local HTML file shown over the terminal.

A ``browser`` action marks a point in its scene, like an overlay. Headless Chromium
(VHS records with it, so it is already there) captures the page at the video's width.
The view covers the picture under a slim address bar from there until its scene ends
or ``duration_ms`` has passed, and with ``scroll`` moves down the page meanwhile.

The mp4 gets the bar and the page as images for ffmpeg (see ``overlays.filter_graph``);
the cast page shows the same images over the player.
"""

from __future__ import annotations

import base64
import contextlib
import glob
import json
import os
import select
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from narratty.errors import MissingDependencyError, RenderError
from narratty.render.overlays import FADE_MS, OverlayImage
from narratty.render.script import END_CUE, overlay_cue
from narratty.spec.model import Browser, ShowBrowser, Spec, Terminal

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
STARTUP_S = 90
PAGE_HEIGHT_JS = "Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight ?? 0)"


@dataclass(frozen=True)
class View:
    """One browser view as it appears in the output."""

    browser: Browser
    start_ms: int
    end_ms: int


def schedule(spec: Spec, times: Mapping[str, int]) -> list[View]:
    """Every browser view of ``spec`` with its start and end, given scene and cue ``times``.

    A later view in the same scene replaces an earlier one.
    """
    end = times[END_CUE]
    visible = [scene for scene in spec.scenes if not scene.hidden]
    views: list[View] = []
    for number, scene in enumerate(visible):
        scene_end = times[visible[number + 1].id] if number + 1 < len(visible) else end
        for index, action in enumerate(scene.actions):
            if not isinstance(action, ShowBrowser):
                continue
            start = times[overlay_cue(scene.id, index)]
            stop = scene_end
            if action.browser.duration_ms is not None:
                stop = min(stop, start + action.browser.duration_ms)
            if views and views[-1].end_ms > start:
                views[-1] = View(views[-1].browser, views[-1].start_ms, start)
            views.append(View(action.browser, start, stop))
    return [view for view in views if view.end_ms > view.start_ms]


def scaled(views: Sequence[View], factor: float) -> list[View]:
    """``views`` with every time multiplied by ``factor`` (planned → rendered length)."""
    return [View(v.browser, round(v.start_ms * factor), round(v.end_ms * factor)) for v in views]


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


def page_url(url: str, workspace: Path) -> str:
    """``url`` as Chromium loads it: web URLs as they are, files from the workspace."""
    if url.startswith(("http://", "https://", "file://")):
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
    with tempfile.TemporaryDirectory(prefix="narratty-chromium-") as profile:
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
            page_px = tools.call(
                "Runtime.evaluate",
                session,
                expression=PAGE_HEIGHT_JS,
                returnByValue=True,
            )["result"].get("value", view_px)
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
            if process.poll() is None:
                process.kill()
            process.wait()
    return distance


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
    """A captured view: the bar, the page and how far it scrolls."""

    view: View
    bar: Path
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
    width, height = spec.terminal.width, spec.terminal.height
    bar_px = bar_height(spec.terminal)
    view_px = height - bar_px
    shots = []
    for number, view in enumerate(views):
        browser = view.browser
        url = page_url(browser.url, workspace)
        check_network(spec, url)
        page = directory / f"browser-{number}.png"
        scroll_px = capture(url, width, view_px, browser.scroll, browser.load_ms, page, chromium=chromium)
        bar = draw_bar(browser.url, width, bar_px, directory / f"browser-{number}-bar.png")
        shots.append(Shot(view, bar, page, view_px, scroll_px))
    return shots


def images(shots: Sequence[Shot], bar_px: int) -> list[OverlayImage]:
    """Each shot as two images for ffmpeg: the page (scrolling) and the bar above it."""
    result = []
    for shot in shots:
        start, end = shot.view.start_ms, shot.view.end_ms
        result.append(
            OverlayImage(
                shot.page, "0", str(bar_px), start, end, shot.view_px, shot.scroll_px, shot.scroll_ms
            )
        )
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
            "bar": data_url(shot.bar),
            "page": data_url(shot.page),
            "bar_height": round(100 * bar_height(terminal) / width, 3),
            "view_height": round(100 * shot.view_px / width, 3),
            "scroll_by": round(100 * shot.scroll_px / width, 3),
            "fade": FADE_MS / 1000,
        }
        for shot in shots
    ]
