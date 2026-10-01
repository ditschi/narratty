"""Run the demo shell in a service of the project's Compose file (``environment.compose``).

The Compose file is read from the workspace, so the services' relative mounts point
at the workspace (a snapshot by default). narratty adds an override file with the
agent, its socket volume, the toolkit and its labels, starts the project with
``compose up --wait`` and removes it afterwards (``down --volumes``). Networks,
mounts and privileges are the Compose file's own.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from narratty.env_container import exec_user
from narratty.environment import (
    AGENT,
    AGENT_DIR,
    RUN_DIR,
    SOCKET,
    Engine,
    Log,
    Mounts,
    Session,
    _check,
    _engine,
    create_run_volume,
    inspect_image,
    serve_agent,
)
from narratty.errors import NarrattyError, UsageError
from narratty.spec.model import Environment

if TYPE_CHECKING:
    from narratty.workspace import PreparedWorkspace


def compose_files(environment: Environment, spec_dir: Path, workspace: PreparedWorkspace) -> list[Path]:
    """The Compose files inside the workspace."""
    assert environment.compose is not None  # noqa: S101
    files = environment.compose.file
    paths = []
    for name in [files] if isinstance(files, str) else files:
        original = (spec_dir / name).resolve()
        try:
            relative = original.relative_to(workspace.source.resolve())
        except ValueError:
            raise UsageError(
                f"the Compose file {original} is outside the workspace {workspace.source}"
            ) from None
        path = workspace.path / relative
        if not path.is_file():
            raise UsageError(f"no Compose file at {original}")
        paths.append(path)
    return paths


def grants(environment: Environment) -> list[str]:
    """What running the Compose project needs approval for."""
    if environment.compose is None:
        return []
    return [
        f"starting the Compose service {environment.compose.service} "
        "with the networks, mounts and privileges of the Compose file (the sandbox rules do not apply to it)"
    ]


def override(
    service: str,
    *,
    image: str | None,
    mounts: Mounts,
    labels: dict[str, str],
) -> dict[str, Any]:
    """The override file narratty adds to the project."""
    entry: dict[str, Any] = {"labels": dict(sorted(labels.items()))}
    volumes: list[str] = []
    top: dict[str, Any] = {"services": {service: entry}}
    if mounts.agent is not None and mounts.volume is not None:
        volumes += [f"{mounts.agent}:{AGENT_DIR}:ro", f"narratty_run:{RUN_DIR}"]
        top["volumes"] = {"narratty_run": {"external": True, "name": mounts.volume}}
    if mounts.toolkit is not None:
        from narratty.env_toolkit import TOOLKIT_DIR

        volumes.append(f"{mounts.toolkit}:{TOOLKIT_DIR}:ro")
    if volumes:
        entry["volumes"] = volumes
    if mounts.access.env:
        entry["environment"] = dict(sorted(mounts.access.env.items()))
    if image is not None:
        entry["image"] = image
        entry["pull_policy"] = "never"
    return top


def _service_image(
    base: list[str], service: str, config: dict[str, Any], project: str, *, rebuild: bool, run: Engine
) -> str:
    """The service's image, built first when the Compose file builds it."""
    entry = config["services"][service]
    if "build" in entry:
        _check(run([*base, "build", *(["--no-cache"] if rebuild else []), service]), f"building {service}")
        return str(entry.get("image") or f"{project}-{service}")
    if not entry.get("image"):
        raise UsageError(f"the Compose service {service} has neither image nor build")
    return str(entry["image"])


def _up(base: list[str], override_file: Path, service: str, *, rebuild: bool, run: Engine) -> str:
    """Start the project; returns the service's container."""
    build = ["--build"] if rebuild else []
    up = run([*base, "--file", str(override_file), "up", "--detach", "--wait", *build, service])
    if up.returncode != 0:
        output = (up.stderr or up.stdout).strip()
        raise NarrattyError(f"starting the Compose service {service} failed: {output}")
    found = _check(run([*base, "ps", "--quiet", service]), "finding the service")
    container = next(iter(found.stdout.split()), "")
    if not container:
        raise NarrattyError(f"the Compose service {service} is not running")
    return container


@contextmanager
def start_compose(
    environment: Environment,
    *,
    spec_dir: Path,
    workspace: PreparedWorkspace,
    engine: str,
    mounts: Mounts,
    agent_for: Callable[[str], Path | None],
    name: str | None = None,
    keep: bool = False,
    rebuild: bool = False,
    run: Engine = _engine,
    log: Log | None = None,
) -> Iterator[Session]:
    """Start the Compose project and reach the shell of ``environment.compose.service``."""
    from narratty.env_image import build_layer
    from narratty.environment import add_toolkit
    from narratty.paths import cache_dir

    assert environment.compose is not None  # noqa: S101
    service = environment.compose.service
    files = compose_files(environment, spec_dir, workspace)
    project = name or f"narratty-{uuid.uuid4().hex[:12]}"
    base = [engine, "compose", "--project-name", project]
    base += ["--project-directory", str(files[0].parent)]
    for file in files:
        base += ["--file", str(file)]
    config = json.loads(_check(run([*base, "config", "--format", "json"]), "reading the Compose file").stdout)
    if service not in (config.get("services") or {}):
        raise UsageError(f"the Compose file {environment.compose.file} has no service {service!r}")

    with ExitStack() as cleanup:
        tmp = Path(tempfile.mkdtemp(prefix="narratty-compose-"))
        cleanup.callback(shutil.rmtree, tmp, ignore_errors=True)
        if not keep:
            cleanup.callback(run, [*base, "down", "--volumes", "--remove-orphans", "--rmi", "local"])
        ref = _service_image(base, service, config, project, rebuild=rebuild, run=run)
        image = inspect_image(engine, ref, run=run, log=log)
        layer = None
        if environment.layered:
            layer = build_layer(
                environment, ref, image.id, image.user,
                engine=engine, cache=cache_dir(), run=run, rebuild=rebuild, log=log,
            )  # fmt: skip
        mounts.agent = agent_for(image.architecture)
        if mounts.agent is not None:
            mounts.volume = f"{project}-run"
            mounts.labels["narratty.volume"] = mounts.volume
            create_run_volume(engine, mounts.volume, run)
            if not keep:
                cleanup.callback(run, [engine, "volume", "rm", "--force", mounts.volume])
        add_toolkit(environment, image, mounts, engine=engine, run=run, log=log)
        user = exec_user(environment.user)
        labels = {
            **mounts.labels,
            "narratty.environment": "1",
            "narratty.workdir": environment.workdir or "",
            "narratty.user": user or "",
        }
        extra = tmp / "narratty.override.json"
        extra.write_text(json.dumps(override(service, image=layer, mounts=mounts, labels=labels)), "utf-8")
        if log:
            log(f"starting the Compose service {service}")
        container = _up(base, extra, service, rebuild=rebuild, run=run)
        if mounts.agent is not None:
            serve_agent(engine, container, AGENT, SOCKET, environment.workdir, user=user, run=run)
        yield Session(engine, container, environment.workdir, mounts.volume, user=user)
        if keep and log:
            log(f"kept the Compose project {project}; remove it with `narratty env down`")
