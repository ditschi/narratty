"""Where narratty keeps downloaded voices and cached audio.

``NARRATTY_DATA_DIR`` and ``NARRATTY_CACHE_DIR`` override the platform defaults
(``~/.local/share/narratty`` and ``~/.cache/narratty`` on Linux).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

APP = "narratty"


def data_dir(env: Mapping[str, str] | None = None) -> Path:
    """Directory for downloaded voices and models."""
    env = os.environ if env is None else env
    if override := env.get("NARRATTY_DATA_DIR"):
        return Path(override).expanduser()
    from platformdirs import user_data_path

    return user_data_path(APP)


def cache_dir(env: Mapping[str, str] | None = None) -> Path:
    """Directory for the audio cache and other disposable files."""
    env = os.environ if env is None else env
    if override := env.get("NARRATTY_CACHE_DIR"):
        return Path(override).expanduser()
    from platformdirs import user_cache_path

    return user_cache_path(APP)
