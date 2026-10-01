"""Start the demo shell in a project environment instead of locally.

A bridge is the command that opens a shell in the environment's container:
``narratty-agent connect …`` inside the narratty container, ``docker exec -it …`` on
the host. Both recorders start the shell by name (VHS only accepts fixed shell
names), so narratty puts shims named like the shells first on ``PATH``. Each shim
runs its shell through the bridge and, once that shell exits, a local ``sh``: the
end card is drawn by narratty, which only exists on this side.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path

BRIDGE_ENV = "NARRATTY_BRIDGE"
SHELLS = ("bash", "zsh", "fish", "sh")


def encode(argv: Sequence[str]) -> str:
    """The bridge as the value of ``NARRATTY_BRIDGE``."""
    return json.dumps(list(argv))


def current(env: Mapping[str, str] | None = None) -> list[str] | None:
    """The bridge handed to this process (by the host, when it runs in the container)."""
    value = (os.environ if env is None else env).get(BRIDGE_ENV)
    return [str(part) for part in json.loads(value)] if value else None


def shim(bridge: Sequence[str], shell: str, local_path: str) -> str:
    """Script standing in for ``shell``."""
    return (
        "#!/bin/sh\n"
        "# narratty: the demo shell runs in the project environment.\n"
        f'{shlex.join(bridge)} {shell} "$@"\n'
        f"PATH={shlex.quote(local_path)} exec sh\n"
    )


def shim_env(directory: Path, bridge: Sequence[str], env: Mapping[str, str]) -> dict[str, str]:
    """Write the shims into ``directory``; returns ``env`` with them first on ``PATH``."""
    directory.mkdir(parents=True, exist_ok=True)
    local_path = env.get("PATH", os.defpath)
    for shell in SHELLS:
        path = directory / shell
        path.write_text(shim(bridge, shell, local_path), encoding="utf-8")
        path.chmod(0o755)
    return {**env, "PATH": f"{directory}{os.pathsep}{local_path}"}
