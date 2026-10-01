"""``narratty env``: the spec's project environment on its own."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import (
    AllowDirtyOption,
    AllowHostOption,
    EnvImageOption,
    ImageOption,
    KeepWorkspaceOption,
    NetworkMode,
    NetworkOption,
    RebuildEnvOption,
    RuntimeOption,
    WorkspaceMode,
    WorkspaceModeOption,
    YesOption,
    sandbox_request,
)
from narratty.runtime import ResolvedRuntime, Runtime

env_app = typer.Typer(help="Work with the spec's project environment.", no_args_is_help=True)

if TYPE_CHECKING:
    from narratty.container import SandboxRequest
    from narratty.environment import Session
    from narratty.spec.model import Environment, Spec


def _environment(spec: Path, request: SandboxRequest) -> tuple[Spec, Environment]:
    """The spec and its environment."""
    from narratty.environment import resolve
    from narratty.errors import UsageError
    from narratty.spec import load_spec

    loaded = load_spec(spec)
    environment = resolve(loaded.environment, request.environment)
    if environment is None:
        raise UsageError(
            f"{spec} has no environment", hint="Add an `environment` block, or pass --env-image."
        )
    return loaded, environment


def log(message: str) -> None:
    """Progress on stderr."""
    from narratty.ui.console import err

    err.print(f"[dim]{message}[/]", highlight=False, soft_wrap=True)


@env_app.command("build")
def build_command(
    spec: Path = SpecArgument,
    env_image: str | None = EnvImageOption,
    rebuild_env: bool = RebuildEnvOption,
    yes: bool = YesOption,
) -> None:
    """Build the environment's image (packages, setup) ahead of a recording."""
    from narratty.container import approved_sandbox
    from narratty.environment import EnvironmentOptions, prepare_image
    from narratty.errors import UsageError
    from narratty.runtime import container_engine
    from narratty.ui.console import out

    env = EnvironmentOptions(image=env_image, rebuild=rebuild_env)
    request = sandbox_request(None, False, False, None, None, yes, env)
    loaded, environment = _environment(spec, request)
    if environment.image is None:
        raise UsageError(
            "env build only applies to environment.image",
            hint="A Compose service is built by `docker compose build`, or on its first run.",
        )
    approved_sandbox(spec, loaded, request)
    image = prepare_image(
        environment, spec_dir=spec.resolve().parent, engine=container_engine(), rebuild=rebuild_env, log=log
    )
    out.print(image.ref, highlight=False)


def _shell_argv(session: Session, resolved: ResolvedRuntime, narratty_image: str, shell: str) -> list[str]:
    import os

    from narratty.container import ContainerSpec, run_argv
    from narratty.environment import RECORDER_AGENT

    if not resolved.sandboxed:
        return [*session.exec_bridge(), shell]
    # Through the agent, from a narratty container.
    volumes, network = session.recorder_flags()
    connect = ContainerSpec(
        resolved.runtime,
        narratty_image,
        session.agent_bridge()[1:] + [shell],
        [],
        {"TERM": os.environ.get("TERM", "xterm-256color")},
        network=network or "none",
        tty=True,
        volumes=volumes,
        entrypoint=RECORDER_AGENT,
        interactive=True,
    )
    return run_argv(connect)


@contextmanager
def _started(
    spec: Path,
    request: SandboxRequest,
    resolved: ResolvedRuntime,
    narratty_image: str,
    *,
    keep: bool = False,
    labels: dict[str, str] | None = None,
    name: str | None = None,
) -> Iterator[tuple[Spec, Session]]:
    from narratty.build import Plan
    from narratty.container import approved_sandbox
    from narratty.env_provide import provide
    from narratty.paths import cache_dir
    from narratty.runtime import container_engine
    from narratty.workspace import prepare_workspace

    loaded, environment = _environment(spec, request)
    sandbox = approved_sandbox(spec, loaded, request)
    with prepare_workspace(
        Plan.source_of(spec, loaded),
        request.workspace.mode or loaded.workspace.mode,
        scratch=cache_dir() / "workspaces",
        include_uncommitted=loaded.workspace.include_uncommitted,
        allow_dirty=request.workspace.allow_dirty,
        keep=keep or request.workspace.keep,
        in_container=True,
        log=log,
    ) as prepared:
        extra = dict(labels or {})
        if labels is not None:
            extra["narratty.workspace"] = str(prepared.path)
            if prepared.snapshot_root is not None:
                extra["narratty.snapshot"] = str(prepared.snapshot_root)
        with provide(
            environment,
            loaded,
            spec_dir=spec.resolve().parent,
            sandbox=sandbox,
            workspace=prepared,
            engine=resolved.runtime.value if resolved.sandboxed else container_engine(),
            narratty_image=narratty_image,
            with_agent=resolved.sandboxed,
            keep=keep,
            rebuild=request.environment.rebuild,
            labels=extra,
            name=name,
            log=log,
        ) as session:
            yield loaded, session


@env_app.command("shell")
def shell_command(
    spec: Path = SpecArgument,
    workspace_mode: WorkspaceMode | None = WorkspaceModeOption,
    keep_workspace: bool = KeepWorkspaceOption,
    allow_dirty: bool = AllowDirtyOption,
    network: NetworkMode | None = NetworkOption,
    allow_host: list[str] | None = AllowHostOption,
    env_image: str | None = EnvImageOption,
    rebuild_env: bool = RebuildEnvOption,
    yes: bool = YesOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Open an interactive shell in the environment, the way the recording gets it.

    Uses the environment `narratty env up` started, if there is one.
    """
    import subprocess

    from narratty.container import image_ref
    from narratty.environment import EnvironmentOptions, running
    from narratty.runtime import container_engine, resolve_runtime

    env = EnvironmentOptions(image=env_image, rebuild=rebuild_env)
    request = sandbox_request(workspace_mode, keep_workspace, allow_dirty, network, allow_host, yes, env)
    loaded, _ = _environment(spec, request)
    resolved = resolve_runtime(runtime)
    narratty_image = image_ref(override=image)
    engine = resolved.runtime.value if resolved.sandboxed else container_engine()
    if (kept := running(engine, spec)) is not None:
        argv = _shell_argv(kept[0], resolved, narratty_image, loaded.terminal.shell)
        raise typer.Exit(subprocess.run(argv, check=False).returncode)  # noqa: S603
    with _started(spec, request, resolved, narratty_image) as (loaded, session):
        argv = _shell_argv(session, resolved, narratty_image, loaded.terminal.shell)
        code = subprocess.run(argv, check=False).returncode  # noqa: S603
    raise typer.Exit(code)


@env_app.command("up")
def up_command(
    spec: Path = SpecArgument,
    workspace_mode: WorkspaceMode | None = WorkspaceModeOption,
    allow_dirty: bool = AllowDirtyOption,
    network: NetworkMode | None = NetworkOption,
    allow_host: list[str] | None = AllowHostOption,
    env_image: str | None = EnvImageOption,
    rebuild_env: bool = RebuildEnvOption,
    yes: bool = YesOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Start the environment and keep it; build, render and env shell use it until `env down`."""
    from narratty.container import image_ref
    from narratty.environment import EnvironmentOptions, running, spec_key
    from narratty.errors import UsageError
    from narratty.runtime import container_engine, resolve_runtime
    from narratty.ui.console import out

    env = EnvironmentOptions(image=env_image, rebuild=rebuild_env)
    request = sandbox_request(workspace_mode, False, allow_dirty, network, allow_host, yes, env)
    _loaded, environment = _environment(spec, request)
    if environment.container is not None:
        raise UsageError("the environment is a running container already; there is nothing to start")
    resolved = resolve_runtime(runtime)
    engine = resolved.runtime.value if resolved.sandboxed else container_engine()
    if (kept := running(engine, spec)) is not None:
        out.print(kept[0].container, highlight=False)
        return
    key = spec_key(spec)
    name = f"narratty-env-{key}"
    labels = {"narratty.spec": key, "narratty.name": name}
    with _started(
        spec, request, resolved, image_ref(override=image), keep=True, labels=labels, name=name
    ) as (
        _spec,
        session,
    ):
        out.print(session.container, highlight=False)


@env_app.command("down")
def down_command(spec: Path = SpecArgument, runtime: Runtime = RuntimeOption) -> None:
    """Remove the environment `narratty env up` started (container, volumes, workspace snapshot)."""
    from narratty.environment import down
    from narratty.runtime import container_engine, resolve_runtime

    resolved = resolve_runtime(runtime)
    engine = resolved.runtime.value if resolved.sandboxed else container_engine()
    if down(engine, spec, log=log) == 0:
        log("no environment is running for this spec")
