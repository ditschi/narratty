"""Where narratty keeps downloaded voices and cached audio.

``NARRATTY_DATA_DIR`` and ``NARRATTY_CACHE_DIR`` override the platform defaults
(``~/.local/share/narratty`` and ``~/.cache/narratty`` on Linux).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

APP = "narratty"

# The container's output directory, mounted from the directory of the requested output.
CONTAINER_OUTPUT = "/out"
# The host directory mounted at CONTAINER_OUTPUT, so messages name the files you get.
HOST_OUTPUT_ENV = "NARRATTY_HOST_OUTPUT"


def host_path(path: Path) -> Path:
    """``path`` as the host sees it, when it is in the container's output directory."""
    host = os.environ.get(HOST_OUTPUT_ENV)
    if not host or not path.is_relative_to(CONTAINER_OUTPUT):
        return path
    return Path(host) / path.relative_to(CONTAINER_OUTPUT)


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
