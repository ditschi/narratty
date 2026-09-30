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
from typing import TYPE_CHECKING

from narratty import __version__
from narratty.runtime import Runtime

if TYPE_CHECKING:
    from narratty.build import WorkspaceOptions
    from narratty.spec.model import Spec

IMAGE_REPOSITORY = "ghcr.io/ditschi/narratty"
_RELEASE = re.compile(r"^\d+\.\d+\.\d+$")

Runner = Callable[[Sequence[str]], int]


def image_ref(*, version: str = __version__, override: str | None = None) -> str:
    """The image for this narratty version (``:edge`` for development builds).

    It contains Kokoro and Piper. ``--image`` / ``NARRATTY_IMAGE`` override it.
    """
    override = override or os.environ.get("NARRATTY_IMAGE")
    if override:
        return override
    tag = version if _RELEASE.match(version) else "edge"
    return f"{IMAGE_REPOSITORY}:{tag}"


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
    volumes: Sequence[str] = ()


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
    for volume in spec.volumes:
        argv += ["--volume", volume]
    for key, value in sorted(spec.env.items()):
        argv += ["--env", f"{key}={value}"]
    return [*argv, spec.image, *spec.args]


def _run(argv: Sequence[str]) -> int:
    return subprocess.run(list(argv), check=False).returncode  # noqa: S603


def run(spec: ContainerSpec, *, runner: Runner | None = None) -> int:
    """Run the container, streaming its output; returns its exit code."""
    return (runner or _run)(run_argv(spec))


def stdout_is_tty() -> bool:
    """Allocate a TTY only when a person is watching (keeps Rich output sane)."""
    return sys.stdout.isatty() and sys.stderr.isatty()


CONTAINER_WORKSPACE = "/work"


@dataclass(frozen=True)
class SandboxRequest:
    """Command-line input for commands that run the demo (build, render)."""

    workspace: WorkspaceOptions = field(default_factory=lambda: _default_workspace_options())
    network: str | None = None
    allow_hosts: tuple[str, ...] = ()
    assume_yes: bool = False


def _default_workspace_options() -> WorkspaceOptions:
    from narratty.build import WorkspaceOptions

    return WorkspaceOptions()


def delegate(
    command: str,
    spec_path: Path,
    *,
    runtime: Runtime,
    image: str | None = None,
    output: Path | None = None,
    work_dir: Path | None = None,
    extra_args: Sequence[str] = (),
    sandbox: SandboxRequest | None = None,
    runner: Runner | None = None,
) -> int | None:
    """Run ``narratty <command>`` in a container when ``runtime`` resolves to one.

    ``sandbox`` is given for commands that run the demo; they get the prepared
    workspace and the spec's sandbox permissions. Returns the container's exit code,
    or None when the command should run natively.
    """
    from narratty.doctor import CONTAINER_TOOLS
    from narratty.errors import MissingDependencyError
    from narratty.runtime import resolve_runtime
    from narratty.spec import load_spec

    resolved = resolve_runtime(runtime)
    if not resolved.sandboxed:
        return None
    tool = CONTAINER_TOOLS[resolved.runtime]
    if not _which(tool.name):
        raise MissingDependencyError(
            f"{tool.name} is not installed", hint=f"{tool.install_hint}, or use --runtime native."
        )
    spec = load_spec(spec_path)  # fail fast on the host, with host paths in the messages
    if "--draft" not in extra_args:
        _ensure_voice(spec.tts.provider, spec.tts.voice)
    chosen_image = image_ref(override=image)
    base = _Invocation(command, spec_path.resolve(), resolved.runtime, chosen_image, extra_args)
    if output is not None:
        base.add_output(output)
    if work_dir is not None:
        base.add_work_dir(work_dir)
    if sandbox is None:
        return run(base.container(), runner=runner)
    return _run_demo(base, spec, sandbox, runner)


def _ensure_voice(provider_name: str, voice: str) -> None:
    from narratty.paths import data_dir
    from narratty.tts.registry import get_provider

    provider = get_provider(provider_name, data_dir())
    if not provider.is_installed(voice):
        provider.install(voice)  # the container has no network


class _Invocation:
    """Collects mounts, environment and arguments for one container run."""

    def __init__(
        self, command: str, spec_file: Path, engine: Runtime, image: str, extra: Sequence[str]
    ) -> None:
        from narratty.paths import cache_dir, data_dir
        from narratty.tts.lexicon import ENV_OVERRIDE, export_host_entries

        cache, data = cache_dir(), data_dir()
        for directory in (cache, data):
            directory.mkdir(parents=True, exist_ok=True)
        self.engine, self.image = engine, image
        self.mounts = [
            Mount(spec_file, f"/spec/{spec_file.name}", read_only=True),
            Mount(cache.resolve(), "/cache"),
            Mount(data.resolve(), "/data", read_only=True),
        ]
        self.volumes: list[str] = []
        self.args = [command, f"/spec/{spec_file.name}", "--runtime", "native", "--offline", *extra]
        self.env = {"NARRATTY_DATA_DIR": "/data", "NARRATTY_CACHE_DIR": "/cache"}
        # The user's and the project's lexicon files are not mounted; hand over their merged entries.
        lexicon = export_host_entries(spec_file, cache / "lexicons")
        self.env[ENV_OVERRIDE] = f"/cache/lexicons/{lexicon.name}"
        self.network = "none"

    def add_output(self, output: Path) -> None:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.mounts.append(Mount(output.parent, "/out"))
        self.args += ["--output", f"/out/{output.name}"]

    def add_work_dir(self, work_dir: Path) -> None:
        work_dir.mkdir(parents=True, exist_ok=True)
        self.mounts.append(Mount(work_dir.resolve(), "/keep"))
        self.args += ["--work-dir", "/keep"]

    def container(self) -> ContainerSpec:
        return ContainerSpec(
            self.engine,
            self.image,
            self.args,
            self.mounts,
            self.env,
            self.network,
            stdout_is_tty(),
            self.volumes,
        )


def _run_demo(invocation: _Invocation, spec: Spec, request: SandboxRequest, runner: Runner | None) -> int:
    import sys

    import typer

    from narratty.build import Plan
    from narratty.paths import cache_dir
    from narratty.sandbox import (
        allowlist_network,
        apply_overrides,
        check_policy,
        container_access,
        ensure_consent,
        load_policy,
    )
    from narratty.ui.console import err
    from narratty.workspace import prepare_workspace

    spec_file = invocation.mounts[0].host
    sandbox = apply_overrides(spec.sandbox, network=request.network, allow_hosts=request.allow_hosts)
    check_policy(sandbox, load_policy())
    ensure_consent(
        spec_file,
        sandbox,
        assume_yes=request.assume_yes,
        interactive=sys.stdin.isatty(),
        confirm=lambda question: typer.confirm(question, default=False, err=True),
    )
    access = container_access(
        sandbox, spec_dir=spec_file.parent, caches=spec.workspace.caches, cache_root=cache_dir()
    )
    invocation.env.update(access.env)
    invocation.volumes += access.volumes
    invocation.network = access.network
    invocation.env["NARRATTY_WORKSPACE"] = CONTAINER_WORKSPACE

    def log(message: str) -> None:
        err.print(f"[dim]{message}[/]", highlight=False, soft_wrap=True)

    source = Plan.source_of(spec_file, spec)
    with prepare_workspace(
        source,
        request.workspace.mode or spec.workspace.mode,
        scratch=cache_dir() / "workspaces",
        include_uncommitted=spec.workspace.include_uncommitted,
        allow_dirty=request.workspace.allow_dirty,
        keep=request.workspace.keep,
        in_container=True,
        log=log,
    ) as workspace:
        invocation.mounts.append(Mount(workspace.path, CONTAINER_WORKSPACE, read_only=workspace.read_only))
        if sandbox.network != "allowlist":
            return run(invocation.container(), runner=runner)
        with allowlist_network(invocation.engine.value, invocation.image, sandbox.allow_hosts) as network:
            invocation.network = network
            return run(invocation.container(), runner=runner)


def _which(name: str) -> str | None:
    import shutil

    return shutil.which(name)
