"""Run a narratty command inside the narratty image (Docker or Podman).

The host CLI resolves paths, makes sure the voice is downloaded, then re-invokes
itself in the container with ``--runtime native``. The container gets:

- the spec read-only at ``/spec/<name>``
- the workspace at ``/work`` (``NARRATTY_WORKSPACE`` points the spec there)
- the output directory at ``/out``
- the host audio cache at ``/cache`` and the host voices read-only at ``/data``

and runs hardened: no network, all capabilities dropped, read-only root filesystem.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from narratty import __version__
from narratty.runtime import Runtime

IMAGE_REPOSITORY = "ghcr.io/ditschi/narratty"
_RELEASE = re.compile(r"^\d+\.\d+\.\d+$")

Runner = Callable[[Sequence[str]], int]


def image_ref(provider: str, *, version: str = __version__, override: str | None = None) -> str:
    """The image for this narratty version (``:edge`` for development builds).

    Kokoro needs the ``-kokoro`` variant. ``--image`` / ``NARRATTY_IMAGE`` override it.
    """
    override = override or os.environ.get("NARRATTY_IMAGE")
    if override:
        return override
    tag = version if _RELEASE.match(version) else "edge"
    return f"{IMAGE_REPOSITORY}:{tag}{'-kokoro' if provider == 'kokoro' else ''}"


@dataclass(frozen=True)
class Mount:
    """A bind mount."""

    host: Path
    container: str
    read_only: bool = False

    def flag(self) -> str:
        """``--volume`` value."""
        return f"{self.host}:{self.container}" + (":ro" if self.read_only else "")


@dataclass(frozen=True)
class ContainerSpec:
    """Everything needed to build the ``docker run`` / ``podman run`` command."""

    engine: Runtime
    image: str
    args: Sequence[str]
    mounts: Sequence[Mount]
    env: dict[str, str] = field(default_factory=dict)
    network: str = "none"
    tty: bool = False


def _user_flags(engine: Runtime) -> list[str]:
    if engine is Runtime.PODMAN:
        return ["--userns", "keep-id"]
    if hasattr(os, "getuid"):
        return ["--user", f"{os.getuid()}:{os.getgid()}"]
    return []  # pragma: no cover - Windows


def run_argv(spec: ContainerSpec) -> list[str]:
    """The full container command line."""
    argv = [
        spec.engine.value, "run", "--rm", "--init",
        "--network", spec.network,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:rw,exec,mode=1777",
        "--tmpfs", "/home/narratty:rw,mode=1777",
        "--shm-size", "1g",
        "--workdir", "/work",
        *_user_flags(spec.engine),
    ]  # fmt: skip
    if spec.tty:
        argv += ["--tty"]
    for mount in spec.mounts:
        argv += ["--volume", mount.flag()]
    for key, value in sorted(spec.env.items()):
        argv += ["--env", f"{key}={value}"]
    return [*argv, spec.image, *spec.args]


def _run(argv: Sequence[str]) -> int:
    return subprocess.run(list(argv), check=False).returncode  # noqa: S603


def run(spec: ContainerSpec, *, runner: Runner = _run) -> int:
    """Run the container, streaming its output; returns its exit code."""
    return runner(run_argv(spec))


def stdout_is_tty() -> bool:
    """Allocate a TTY only when a person is watching (keeps Rich output sane)."""
    return sys.stdout.isatty() and sys.stderr.isatty()


CONTAINER_WORKSPACE = "/work"


def delegate(
    command: str,
    spec_path: Path,
    *,
    runtime: Runtime,
    image: str | None = None,
    output: Path | None = None,
    work_dir: Path | None = None,
    extra_args: Sequence[str] = (),
    runner: Runner = _run,
) -> int | None:
    """Run ``narratty <command>`` in a container when ``runtime`` resolves to one.

    Returns the container's exit code, or None when the command should run natively.
    """
    from narratty.doctor import CONTAINER_TOOLS
    from narratty.errors import MissingDependencyError
    from narratty.paths import cache_dir, data_dir
    from narratty.runtime import resolve_runtime
    from narratty.spec import load_spec
    from narratty.tts.registry import get_provider

    resolved = resolve_runtime(runtime)
    if not resolved.sandboxed:
        return None
    tool = CONTAINER_TOOLS[resolved.runtime]
    if not _which(tool.name):
        raise MissingDependencyError(
            f"{tool.name} is not installed", hint=f"{tool.install_hint}, or use --runtime native."
        )

    spec = load_spec(spec_path)  # fail fast on the host, with host paths in the messages
    provider = get_provider(spec.tts.provider, data_dir())
    if not provider.is_installed(spec.tts.voice):
        provider.install(spec.tts.voice)  # the container has no network

    spec_file = spec_path.resolve()
    workspace = (spec_file.parent / spec.workspace.source).resolve()
    cache, data = cache_dir(), data_dir()
    for directory in (cache, data):
        directory.mkdir(parents=True, exist_ok=True)
    mounts = [
        Mount(spec_file, f"/spec/{spec_file.name}", read_only=True),
        Mount(workspace, CONTAINER_WORKSPACE),
        Mount(cache.resolve(), "/cache"),
        Mount(data.resolve(), "/data", read_only=True),
    ]
    args = [command, f"/spec/{spec_file.name}", "--runtime", "native", "--offline", *extra_args]
    if output is not None:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        mounts.append(Mount(output.parent, "/out"))
        args += ["--output", f"/out/{output.name}"]
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
        mounts.append(Mount(work_dir.resolve(), "/keep"))
        args += ["--work-dir", "/keep"]
    env = {
        "NARRATTY_WORKSPACE": CONTAINER_WORKSPACE,
        "NARRATTY_DATA_DIR": "/data",
        "NARRATTY_CACHE_DIR": "/cache",
    }
    container = ContainerSpec(
        resolved.runtime,
        image_ref(spec.tts.provider, override=image),
        args,
        mounts,
        env,
        tty=stdout_is_tty(),
    )
    return run(container, runner=runner)


def _which(name: str) -> str | None:
    import shutil

    return shutil.which(name)
