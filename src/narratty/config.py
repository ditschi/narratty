"""The user's configuration file, ``~/.config/narratty/config.toml``."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from narratty.errors import UsageError


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    """``~/.config/narratty`` (``NARRATTY_CONFIG_DIR`` overrides it)."""
    env = os.environ if env is None else env
    if override := env.get("NARRATTY_CONFIG_DIR"):
        return Path(override).expanduser()
    from platformdirs import user_config_path

    return user_config_path("narratty")


def config_file(directory: Path | None = None) -> Path:
    """Path of ``config.toml``."""
    return (directory or config_dir()) / "config.toml"


def config_section(name: str, directory: Path | None = None) -> dict[str, Any]:
    """The ``[name]`` table of config.toml; empty when the file or table is missing."""
    path = config_file(directory)
    if not path.is_file():
        return {}
    try:
        section = tomllib.loads(path.read_text(encoding="utf-8")).get(name, {})
    except tomllib.TOMLDecodeError as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    if not isinstance(section, dict):
        raise UsageError(f"{path}: [{name}] must be a table")
    return section
