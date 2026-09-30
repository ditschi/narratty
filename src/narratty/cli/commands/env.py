"""``narratty env``: the spec's project environment on its own."""

from __future__ import annotations

from pathlib import Path

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
    RuntimeOption,
    WorkspaceMode,
    WorkspaceModeOption,
    YesOption,
    sandbox_request,
)
from narratty.runtime import Runtime

env_app = typer.Typer(help="Work with the spec's project environment.", no_args_is_help=True)


@env_app.command("shell")
def shell_command(
    spec: Path = SpecArgument,
    workspace_mode: WorkspaceMode | None = WorkspaceModeOption,
    keep_workspace: bool = KeepWorkspaceOption,
    allow_dirty: bool = AllowDirtyOption,
    network: NetworkMode | None = NetworkOption,
    allow_host: list[str] | None = AllowHostOption,
    env_image: str | None = EnvImageOption,
    yes: bool = YesOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Open an interactive shell in the environment, the way the recording gets it."""
    import os
    import subprocess

    from narratty.build import Plan
    from narratty.container import ContainerSpec, approved_sandbox, image_ref, run_argv
    from narratty.environment import RECORDER_AGENT, provide, resolve
    from narratty.errors import UsageError
    from narratty.paths import cache_dir
    from narratty.runtime import container_engine, resolve_runtime
    from narratty.spec import load_spec
    from narratty.ui.console import err
    from narratty.workspace import prepare_workspace

    loaded = load_spec(spec)
    request = sandbox_request(
        workspace_mode, keep_workspace, allow_dirty, network, allow_host, yes, env_image
    )
    environment = resolve(loaded.environment, request.environment)
    if environment is None:
        raise UsageError(
            f"{spec} has no environment", hint="Add an `environment` block, or pass --env-image."
        )
    sandbox = approved_sandbox(spec, loaded, request)
    resolved = resolve_runtime(runtime)
    engine = resolved.runtime.value if resolved.sandboxed else container_engine()
    narratty_image = image_ref(override=image)

    def log(message: str) -> None:
        err.print(f"[dim]{message}[/]", highlight=False, soft_wrap=True)

    shell = loaded.terminal.shell
    with (
        prepare_workspace(
            Plan.source_of(spec, loaded),
            request.workspace.mode or loaded.workspace.mode,
            scratch=cache_dir() / "workspaces",
            include_uncommitted=loaded.workspace.include_uncommitted,
            allow_dirty=allow_dirty,
            keep=keep_workspace,
            in_container=True,
            log=log,
        ) as prepared,
        provide(
            environment,
            loaded,
            spec_dir=spec.resolve().parent,
            sandbox=sandbox,
            workspace=prepared,
            engine=engine,
            narratty_image=narratty_image,
            with_agent=resolved.sandboxed,
            log=log,
        ) as session,
    ):
        if resolved.sandboxed:  # through the agent, from a narratty container
            connect = ContainerSpec(
                resolved.runtime,
                narratty_image,
                session.agent_bridge()[1:] + [shell],
                [],
                {"TERM": os.environ.get("TERM", "xterm-256color")},
                tty=True,
                volumes=[session.recorder_volume()],
                entrypoint=RECORDER_AGENT,
                interactive=True,
            )
            argv = run_argv(connect)
        else:
            argv = [*session.exec_bridge(), shell]
        code = subprocess.run(argv, check=False).returncode  # noqa: S603
    raise typer.Exit(code)
