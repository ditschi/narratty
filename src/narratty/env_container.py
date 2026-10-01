"""Run the demo shell in a container that is already running (``environment.container``).

narratty neither starts nor stops the container and adds no mounts to it. Natively
the bridge is ``docker exec``. Sandboxed, narratty copies the agent into the
container, serves one shell on an abstract socket and joins the narratty container
to the container's network namespace to reach it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from narratty.environment import (
    ARCHITECTURES,
    Engine,
    Log,
    Session,
    _check,
    _engine,
    host_user,
    serve_agent,
)
from narratty.errors import UsageError
from narratty.spec.model import Environment


def exec_user(user: str) -> str | None:
    """``exec --user`` for ``environment.user`` (``image`` keeps the container's user)."""
    if user == "image":
        return None
    return host_user() if user == "host" else user


def grants(environment: Environment) -> list[str]:
    """What running in the container needs approval for."""
    if environment.container is None:
        return []
    return [
        f"running the demo shell in your container {environment.container} "
        "with its network, mounts and privileges (the sandbox rules do not apply to it)"
    ]


@contextmanager
def attach(
    environment: Environment,
    *,
    engine: str,
    agent_for: Callable[[str], Path | None],
    run: Engine = _engine,
    log: Log | None = None,
) -> Iterator[Session]:
    """Reach the shell of the running ``environment.container``."""
    name = environment.container
    assert name is not None  # noqa: S101
    found = run([engine, "inspect", "--format", "{{json .}}", name])
    state = json.loads(found.stdout) if found.returncode == 0 and found.stdout.strip() else None
    if not state or not (state.get("State") or {}).get("Running"):
        raise UsageError(
            f"the container {name!r} is not running", hint=f"Start it first (`{engine} start {name}`)."
        )
    image = _check(
        run([engine, "image", "inspect", "--format", "{{.Architecture}}", str(state.get("Image", ""))]),
        f"inspecting the image of {name}",
    ).stdout.strip()
    user = exec_user(environment.user)
    agent = agent_for(ARCHITECTURES.get(image, image))
    if agent is None:
        yield Session(engine, name, environment.workdir, user=user)
        return
    token = uuid.uuid4().hex[:12]
    target = f"/tmp/narratty-agent-{token}"  # noqa: S108 - inside the container
    socket = f"@narratty-{token}"
    _check(
        run([engine, "cp", str(agent / "narratty-agent"), f"{name}:{target}"]),
        f"copying narratty-agent to {name}",
    )
    try:
        if log:
            log(f"attaching to {name}")
        serve_agent(engine, name, target, socket, environment.workdir, user=user, once=True, run=run)
        try:
            yield Session(engine, name, environment.workdir, socket=socket, user=user)
        finally:
            # An agent that served no shell still waits; one trivial shell ends it.
            run([engine, "exec", name, target, "connect", "--socket", socket, "--", "true"])
    finally:
        run([engine, "exec", "--user", "0", name, "rm", "-f", target])
