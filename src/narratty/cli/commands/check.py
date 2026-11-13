"""``narratty check``: run a spec's commands and compare what they print with the doc."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import (
    AllowDirtyOption,
    AllowHostOption,
    EnvImageOption,
    IgnoreExitOption,
    ImageOption,
    KeepEnvOption,
    KeepWorkspaceOption,
    NetworkMode,
    NetworkOption,
    NoEnvOption,
    OfflineOption,
    RebuildEnvOption,
    RuntimeOption,
    WorkspaceMode,
    WorkspaceModeOption,
    YesOption,
    sandbox_request,
)
from narratty.runtime import Runtime


def check_command(
    spec: Path = SpecArgument,
    work_dir: Path | None = typer.Option(None, "--work-dir", help="Keep the exit log in this directory."),
    ignore_exit: bool = IgnoreExitOption,
    workspace_mode: WorkspaceMode | None = WorkspaceModeOption,
    keep_workspace: bool = KeepWorkspaceOption,
    allow_dirty: bool = AllowDirtyOption,
    network: NetworkMode | None = NetworkOption,
    allow_host: list[str] | None = AllowHostOption,
    env_image: str | None = EnvImageOption,
    no_env: bool = NoEnvOption,
    keep_env: bool = KeepEnvOption,
    rebuild_env: bool = RebuildEnvOption,
    yes: bool = YesOption,
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Run the commands as the video would, without recording it, and check their exit
    codes and output (expect_output, the output shown in Markdown console blocks)."""
    from narratty.build import check
    from narratty.container import delegate
    from narratty.environment import EnvironmentOptions
    from narratty.ui.console import err

    _ = offline  # no narration is synthesized; accepted like the other commands that run the demo
    env = EnvironmentOptions(no_env, env_image, keep_env, rebuild_env)
    request = sandbox_request(workspace_mode, keep_workspace, allow_dirty, network, allow_host, yes, env)
    code = delegate(
        "check",
        spec,
        runtime=runtime,
        image=image,
        work_dir=work_dir,
        extra_args=["--ignore-exit"] if ignore_exit else [],
        sandbox=request,
        ignore_exit=ignore_exit,
        voice=False,
    )
    if code is not None:
        raise typer.Exit(code)

    from narratty.spec.compile import located

    with err.status("checking") as status, located(spec):

        def log(message: str) -> None:
            status.update(message)
            err.print(f"[dim]{message}[/]", highlight=False, soft_wrap=True)

        result = check(
            spec,
            work_dir=work_dir,
            workspace=request.workspace,
            ignore_exit=ignore_exit,
            sandbox=request,
            log=log,
        )
    runs, compared, shown = result.commands, result.compared, result.shown
    err.print(
        f"[green]ok[/] {runs} command{'s' if runs != 1 else ''} ran"
        + (f", {shown} shown only" if shown else "")
        + f"; {compared} output{'s' if compared != 1 else ''} as expected",
        highlight=False,
        soft_wrap=True,
    )
    if not runs:
        _warn_nothing_ran(spec, shown)


def _warn_nothing_ran(spec: Path, shown: int) -> None:
    """Nothing was checked: say so, with the doc's warnings about commands that do not run."""
    from rich.markup import escape

    from narratty.spec.compile import markdown_warnings
    from narratty.spec.loader import Issue, parse_document, read_spec_text
    from narratty.ui.console import err

    why = f"; {shown} no-run command{'s are' if shown != 1 else ' is'} only typed" if shown else ""
    err.print(
        f"[yellow]warning:[/] no command ran, so none was checked{why}", highlight=False, soft_wrap=True
    )
    for warning in markdown_warnings(parse_document(read_spec_text(spec), spec), spec):
        if "command" in warning.what:
            where = Issue("", warning.what, warning.line, None, warning.file)
            err.print(f"[yellow]warning:[/] {escape(where.render(spec))}", highlight=False, soft_wrap=True)
