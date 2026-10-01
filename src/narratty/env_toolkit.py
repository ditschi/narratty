"""The demo toolkit in project environments.

The toolkit image (``ghcr.io/ditschi/narratty-toolkit``) holds static binaries and
recording defaults. Its files are copied once per image and architecture into the
cache and mounted read-only at ``/.narratty/toolkit``; ``PATH`` and the tools' config
variables point there. Nothing is installed into the project's image.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess

TOOLKIT_DIR = "/.narratty/toolkit"
TOOLKIT_REPOSITORY = "ghcr.io/ditschi/narratty-toolkit"
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

Engine = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
Log = Callable[[str], None]


def toolkit_ref(env: Mapping[str, str] | None = None) -> str:
    """The toolkit image matching this version (``NARRATTY_TOOLKIT_IMAGE`` overrides it)."""
    from narratty.runtime import release_tag

    environ = os.environ if env is None else env
    if override := environ.get("NARRATTY_TOOLKIT_IMAGE"):
        return override
    return f"{TOOLKIT_REPOSITORY}:{release_tag()}"


def toolkit_dir(
    engine: str, architecture: str, *, cache: Path, run: Engine, log: Log | None = None
) -> Path | None:
    """The toolkit's files for ``architecture``, or None when the image is not available."""
    import uuid

    ref = toolkit_ref()
    platform = f"linux/{architecture}"
    inspect = [engine, "image", "inspect", "--format", "{{.Id}}", ref]
    found = run(inspect)
    if found.returncode != 0:
        run([engine, "pull", "--platform", platform, ref])
        found = run(inspect)
        if found.returncode != 0:
            if log:
                log(f"the demo toolkit ({ref}) is not available; running without it")
            return None
    dest = cache / "toolkit" / f"{found.stdout.strip().removeprefix('sha256:')[:16]}-{architecture}"
    if dest.is_dir():
        return dest
    name = f"narratty-toolkit-{uuid.uuid4().hex[:12]}"
    partial = dest.with_name(dest.name + f".{name}")
    try:
        if run([engine, "create", "--platform", platform, "--name", name, ref, "none"]).returncode != 0:
            return None
        partial.mkdir(parents=True)
        if run([engine, "cp", f"{name}:/.", str(partial)]).returncode != 0:
            return None
        partial.rename(dest)
    finally:
        run([engine, "rm", "--force", name])
        if partial.exists():
            import shutil

            shutil.rmtree(partial, ignore_errors=True)
    return dest


def toolkit_env(mode: str, image_path: str | None) -> dict[str, str]:
    """Variables that put the toolkit on ``PATH`` (first or last) and configure its tools."""
    path = image_path or DEFAULT_PATH
    bin_dir = f"{TOOLKIT_DIR}/bin"
    share = f"{TOOLKIT_DIR}/share/narratty"
    return {
        "PATH": f"{bin_dir}:{path}" if mode == "prefer" else f"{path}:{bin_dir}",
        "NARRATTY_TOOLKIT": share,
        "TERMINFO_DIRS": f"{TOOLKIT_DIR}/share/terminfo:",  # the trailing ':' keeps the defaults
        "YAZI_CONFIG_HOME": f"{share}/yazi",
        "BAT_CONFIG_PATH": f"{share}/bat/config",
    }
