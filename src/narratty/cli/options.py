"""Options shared by several subcommands."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import typer

from narratty.runtime import Runtime

if TYPE_CHECKING:
    from narratty.container import SandboxRequest

RuntimeOption = typer.Option(
    Runtime.AUTO,
    "--runtime",
    "-r",
    envvar="NARRATTY_RUNTIME",
    case_sensitive=False,
    help="Where to run: auto (container if available), native, docker or podman.",
)

OfflineOption = typer.Option(
    False, "--offline", envvar="NARRATTY_OFFLINE", help="Fail instead of downloading a missing voice."
)

ImageOption = typer.Option(
    None,
    "--image",
    envvar="NARRATTY_IMAGE",
    help="Container image to use (default: ghcr.io/ditschi/narratty matching this version).",
)


class WorkspaceMode(StrEnum):
    """Values of ``--workspace-mode``."""

    SNAPSHOT = "snapshot"
    RW = "rw"
    RO = "ro"


class NetworkMode(StrEnum):
    """Values of ``--network``."""

    NONE = "none"
    ALLOWLIST = "allowlist"
    FULL = "full"


WorkspaceModeOption = typer.Option(
    None, "--workspace-mode", help="Override workspace.mode: snapshot (throwaway copy), rw (in place) or ro."
)
KeepWorkspaceOption = typer.Option(False, "--keep-workspace", help="Keep the workspace snapshot afterwards.")
AllowDirtyOption = typer.Option(
    False, "--allow-dirty", help="Allow workspace.mode rw on a work tree with uncommitted changes."
)
NetworkOption = typer.Option(None, "--network", help="Override sandbox.network (containers only).")
AllowHostOption = typer.Option(
    None, "--allow-host", help="Allow HOST:PORT (implies --network allowlist); repeatable."
)
EnvImageOption = typer.Option(
    None, "--env-image", help="Run the demo shell in this image (overrides the spec's environment)."
)
NoEnvOption = typer.Option(
    False, "--no-env", help="Ignore the spec's environment; run the demo in the narratty image."
)
KeepEnvOption = typer.Option(False, "--keep-env", help="Keep the environment's container afterwards.")
YesOption = typer.Option(
    False, "--yes", "-y", envvar="NARRATTY_YES", help="Approve the spec's sandbox permissions without asking."
)


def check_hosts(hosts: list[str] | None) -> tuple[str, ...]:
    """Validate ``--allow-host`` values."""
    import re

    from narratty.errors import UsageError
    from narratty.spec.model import HOST_PORT_PATTERN

    for host in hosts or []:
        if not re.match(HOST_PORT_PATTERN, host):
            raise UsageError(f"--allow-host {host!r} is not HOST:PORT")
    return tuple(hosts or ())


def sandbox_request(  # noqa: PLR0913 - one parameter per shared option
    workspace_mode: WorkspaceMode | None,
    keep_workspace: bool,
    allow_dirty: bool,
    network: NetworkMode | None,
    allow_host: list[str] | None,
    yes: bool,
    env_image: str | None = None,
    no_env: bool = False,
    keep_env: bool = False,
) -> SandboxRequest:
    """The workspace, sandbox and environment options of a command that runs the demo."""
    from narratty.build import WorkspaceOptions
    from narratty.container import SandboxRequest
    from narratty.environment import EnvironmentOptions

    return SandboxRequest(
        WorkspaceOptions(workspace_mode.value if workspace_mode else None, allow_dirty, keep_workspace),
        network.value if network else None,
        check_hosts(allow_host),
        yes,
        EnvironmentOptions(no_env, env_image, keep_env),
    )


EndCardOption = typer.Option(
    None,
    "--end-card/--no-end-card",
    help='Show the closing "Created with narratty" card (default: the spec, then your config, then on).',
    show_default=False,
)
