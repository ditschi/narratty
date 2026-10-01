"""A self-contained HTML page that plays an asciicast with its narration.

asciinema-player (loaded from jsDelivr, pinned and integrity-checked) plays the cast
and uses the audio as its clock, so pausing and seeking keep both in sync. Cast and
audio are embedded, so the page works from disk and on any static host.
"""

from __future__ import annotations

import base64
import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

PLAYER_VERSION = "3.17.0"
_CDN = f"https://cdn.jsdelivr.net/npm/asciinema-player@{PLAYER_VERSION}/dist/bundle"
_JS_SRI = "sha384-s55nTYAdrPwGWmKKQ1lCnoB8H9LbqmsXsqqqPAHK2+T5h9IfI2dTXTDXJcZnySJD"
_CSS_SRI = "sha384-05cmIVRzN7mR7nmqajPpGPUPqJ5VyTAGHL1xJuiGWfhpWDp5hEfBk50kr21f3ILM"

# VHS theme names that asciinema-player ships as well.
PLAYER_THEMES = frozenset(
    {
        "asciinema",
        "dracula",
        "gruvbox-dark",
        "monokai",
        "nord",
        "seti",
        "solarized-dark",
        "solarized-light",
        "tango",
    }
)


def player_theme(vhs_theme: str) -> str | None:
    """The player theme matching ``vhs_theme`` (``Solarized Dark`` → ``solarized-dark``)."""
    name = vhs_theme.strip().lower().replace(" ", "-")
    return name if name in PLAYER_THEMES else None


def _script_json(value: object) -> str:
    """``value`` as JSON that is safe inside a <script> element."""
    return json.dumps(value).replace("</", "<\\/")


_OVERLAY_CSS = """
#stage { position: relative; width: min(100% - 32px, 1100px); container-type: inline-size; }
.overlay {
  position: absolute; z-index: 10; pointer-events: none; white-space: pre-line;
  font-family: "DejaVu Sans", system-ui, sans-serif; line-height: 1.3;
  opacity: 0; transition: opacity 0.2s;
}
.overlay.on { opacity: 1; }
.overlay.box { padding: 0.4em 0.7em; border-radius: 0.45em; }
.overlay:not(.box) { text-shadow: 0 0 0.12em #000, 0 0 0.12em #000, 0 0 0.12em #000; }
"""

_OVERLAY_JS = """
const stage = document.getElementById("stage");
const shown = overlays.map((o) => {
  const el = document.createElement("div");
  el.className = "overlay" + (o.background ? " box" : "");
  el.textContent = o.text;
  const [v, h] = o.position.includes("-") ? o.position.split("-")
    : ["top", "bottom"].includes(o.position) ? [o.position, "center"] : ["center", o.position];
  const s = el.style, m = o.margin + "cqw";
  s.fontSize = o.size + "cqw"; s.color = o.color; s.fontWeight = o.bold ? "bold" : "normal";
  if (o.background) s.background = o.background;
  const [dx, dy] = [h === "center" ? "-50%" : "0", v === "center" ? "-50%" : "0"];
  if (h === "center") s.left = "50%"; else s[h] = m;
  if (v === "center") s.top = "50%"; else s[v] = m;
  s.translate = dx + " " + dy;
  stage.appendChild(el);
  return el;
});
async function tick() {
  const t = await player.getCurrentTime();
  overlays.forEach((o, i) => shown[i].classList.toggle("on", t >= o.start && t < o.end));
  requestAnimationFrame(tick);
}
if (overlays.length) tick();
"""


_BROWSER_CSS = """
.browser {
  position: absolute; inset: 0; z-index: 5; overflow: hidden; background: #fff;
  pointer-events: none; opacity: 0; transition: opacity 0.2s;
}
.browser.on { opacity: 1; }
.browser img { display: block; width: 100%; }
.browser .view { overflow: hidden; }
"""

_BROWSER_JS = """
const views = browsers.map((b) => {
  const el = document.createElement("div");
  el.className = "browser";
  el.innerHTML = '<img class="bar" alt=""><div class="view"><img class="page" alt=""></div>';
  el.querySelector(".bar").src = b.bar;
  el.querySelector(".page").src = b.page;
  el.querySelector(".view").style.height = b.view_height + "cqw";
  stage.appendChild(el);
  return el;
});
async function browse() {
  const t = await player.getCurrentTime();
  browsers.forEach((b, i) => {
    views[i].classList.toggle("on", t >= b.start && t < b.end);
    const [from, to] = b.scroll;
    const p = Math.min(1, Math.max(0, (t - from) / Math.max(to - from, 0.001)));
    views[i].querySelector(".page").style.translate = "0 " + (-p * b.scroll_by) + "cqw";
  });
  requestAnimationFrame(browse);
}
if (browsers.length) browse();
"""


def player_page(
    title: str,
    cast: str,
    audio: Path,
    *,
    theme: str | None = None,
    overlays: Sequence[Mapping[str, object]] = (),
    browsers: Sequence[Mapping[str, object]] = (),
) -> str:
    """The page for ``cast`` with ``audio`` (MP3) embedded as a data URL.

    ``overlays`` (see ``narratty.render.overlays.page_overlays``) are drawn over the
    player and follow its clock, as do ``browsers`` (see
    ``narratty.render.browser.page_views``), below the overlays.
    """
    audio_url = "data:audio/mpeg;base64," + base64.b64encode(audio.read_bytes()).decode("ascii")
    options: dict[str, object] = {"audioUrl": audio_url, "fit": "width", "preload": True}
    if theme:
        options["theme"] = theme
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{_CDN}/asciinema-player.css" integrity="{_CSS_SRI}" crossorigin="anonymous">
<style>
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #1e1e1e; }}
{_OVERLAY_CSS}{_BROWSER_CSS}</style>
</head>
<body>
<div id="stage"><div id="player"></div></div>
<script src="{_CDN}/asciinema-player.min.js" integrity="{_JS_SRI}" crossorigin="anonymous"></script>
<script>
const player = AsciinemaPlayer.create(
  {{ data: {_script_json(cast)} }}, document.getElementById("player"), {_script_json(options)}
);
const overlays = {_script_json(list(overlays))};
const browsers = {_script_json(list(browsers))};
{_OVERLAY_JS}{_BROWSER_JS}</script>
</body>
</html>
"""
