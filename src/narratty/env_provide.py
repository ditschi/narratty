"""Start the spec's environment, whatever its source (image, build, Compose, container)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from narratty import env_compose, env_container, env_image
from narratty.env_compose import start_compose
from narratty.env_container import attach
from narratty.environment import (
    Engine,
    Log,
    Mounts,
    Session,
    _engine,
    add_toolkit,
    agent_dir,
    home_for,
    prepare_image,
    start,
)
from narratty.spec.model import Environment, Sandbox, Spec

if TYPE_CHECKING:
    from narratty.workspace import PreparedWorkspace


def grants(environment: Environment) -> list[str]:
    """What the environment needs approval for beyond the sandbox rules."""
    return [
        *env_image.grants(environment),
        *env_compose.grants(environment),
        *env_container.grants(environment),
    ]


@contextmanager
def provide(
    environment: Environment,
    spec: Spec,
    *,
    spec_dir: Path,
    sandbox: Sandbox,
    workspace: PreparedWorkspace,
    engine: str,
    narratty_image: str,
    with_agent: bool,
    keep: bool = False,
    rebuild: bool = False,
    labels: dict[str, str] | None = None,
    name: str | None = None,
    run: Engine = _engine,
    log: Log | None = None,
) -> Iterator[Session]:
    """Start ``environment`` for ``spec`` under the (already approved) ``sandbox`` rules.

    ``narratty_image`` supplies the agent (``with_agent``) and the allowlist forwarders.
    ``labels`` and ``name`` mark an environment kept for later runs (``env up``).
    """
    from narratty.paths import cache_dir
    from narratty.sandbox import ContainerAccess, allowlist_network, container_access

    def agent_for(architecture: str) -> Path | None:
        if not with_agent:
            return None
        return agent_dir(engine, narratty_image, architecture, cache=cache_dir(), run=run)

    if environment.container is not None:
        with attach(environment, engine=engine, agent_for=agent_for, run=run, log=log) as session:
            yield session
        return
    if environment.compose is not None:
        mounts = Mounts(ContainerAccess(env=dict(sandbox.env)), labels=dict(labels or {}))
        with start_compose(
            environment, spec_dir=spec_dir, workspace=workspace, engine=engine, mounts=mounts,
            agent_for=agent_for, name=name, keep=keep, rebuild=rebuild, run=run, log=log,
        ) as session:  # fmt: skip
            yield session
        return
    image = prepare_image(environment, spec_dir=spec_dir, engine=engine, rebuild=rebuild, run=run, log=log)
    access = container_access(
        sandbox,
        spec_dir=spec_dir,
        caches=spec.workspace.caches,
        cache_root=cache_dir(),
        home=home_for(environment, image),
    )
    mounts = Mounts(access, agent=agent_for(image.architecture), labels=dict(labels or {}))
    add_toolkit(environment, image, mounts, engine=engine, run=run, log=log)
    launch = partial(
        start, environment, image, engine=engine, shell=spec.terminal.shell, workspace=workspace,
        mounts=mounts, name=name, keep=keep, run=run, log=log,
    )  # fmt: skip
    if sandbox.network != "allowlist":
        with launch(network=access.network) as session:
            yield session
        return
    with (
        allowlist_network(engine, narratty_image, sandbox.allow_hosts) as network,
        launch(network=network) as session,
    ):
        yield session
