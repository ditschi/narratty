"""A self-contained HTML page that plays an asciicast with its narration.

asciinema-player (loaded from jsDelivr, pinned and integrity-checked) plays the cast
and uses the audio as its clock, so pausing and seeking keep both in sync. Cast and
audio are embedded, so the page works from disk and on any static host.
"""

from __future__ import annotations

import base64
import html
import json
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


def player_page(title: str, cast: str, audio: Path, *, theme: str | None = None) -> str:
    """The page for ``cast`` with ``audio`` (MP3) embedded as a data URL."""
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
#player {{ width: min(100% - 32px, 1100px); }}
</style>
</head>
<body>
<div id="player"></div>
<script src="{_CDN}/asciinema-player.min.js" integrity="{_JS_SRI}" crossorigin="anonymous"></script>
<script>
AsciinemaPlayer.create(
  {{ data: {_script_json(cast)} }}, document.getElementById("player"), {_script_json(options)}
);
</script>
</body>
</html>
"""
