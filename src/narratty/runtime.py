"""Runtime selection: where the pipeline runs (natively or in a container)."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

Which = Callable[[str], str | None]

IN_CONTAINER_ENV = "NARRATTY_IN_CONTAINER"


class Runtime(StrEnum):
    """Runtimes a user can request with ``--runtime`` / ``NARRATTY_RUNTIME``."""

    AUTO = "auto"
    NATIVE = "native"
    DOCKER = "docker"
    PODMAN = "podman"


@dataclass(frozen=True)
class ResolvedRuntime:
    """The concrete runtime chosen for this run and why."""

    runtime: Runtime
    reason: str
    sandboxed: bool


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_runtime(
    requested: Runtime,
    *,
    which: Which | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedRuntime:
    """Resolve ``requested`` to a concrete runtime.

    ``auto`` picks native inside the narratty container, otherwise Docker, then
    Podman, and falls back to native (unsandboxed) when neither is installed.
    An explicit runtime is returned as is; ``doctor`` checks it is available.
    """
    environ = os.environ if env is None else env
    lookup = shutil.which if which is None else which
    if requested is not Runtime.AUTO:
        return ResolvedRuntime(requested, "requested explicitly", requested is not Runtime.NATIVE)
    if _truthy(environ.get(IN_CONTAINER_ENV)):
        return ResolvedRuntime(Runtime.NATIVE, "already inside the narratty container", False)
    for candidate in (Runtime.DOCKER, Runtime.PODMAN):
        if lookup(candidate.value):
            return ResolvedRuntime(candidate, f"{candidate.value} found on PATH", True)
    return ResolvedRuntime(
        Runtime.NATIVE,
        "no container runtime found, running natively (not sandboxed)",
        False,
    )
