"""Project environments: run the demo shell in the project's own container.

Only the shell moves; VHS, Chromium, TTS and ffmpeg stay where they are. narratty
starts the environment's container with the terminal shell as a placeholder
process, mounts the workspace at ``environment.workdir`` and applies the sandbox
rules (network, capabilities, environment, mounts) to it.

- **Sandboxed runtime:** the static ``narratty-agent`` (taken from the narratty
  image) is mounted read-only into the container and serves a pseudo-terminal on a
  socket in a small shared volume. The narratty container connects to it; it keeps
  no network and no access to the container runtime.
- **Native runtime:** the host has Docker or Podman, so ``docker exec -it`` is the
  bridge.

See ``narratty.bridge`` for how the recorders use the bridge.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from narratty.errors import MissingDependencyError, NarrattyError, UsageError
from narratty.spec.model import ENV_SOURCES, Environment, Sandbox, Spec

if TYPE_CHECKING:
    from narratty.sandbox import ContainerAccess
    from narratty.workspace import PreparedWorkspace

AGENT_DIR = "/.narratty/agent"
RUN_DIR = "/.narratty/run"
AGENT = f"{AGENT_DIR}/narratty-agent"
SOCKET = f"{RUN_DIR}/agent.sock"
# Where the narratty container mounts the run volume, and its own agent.
RECORDER_RUN_DIR = "/run/narratty"
RECORDER_AGENT = "narratty-agent"
IMAGE_AGENT_DIR = "/opt/narratty/agent"
HOST_HOME = "/home/narratty"
ARCHITECTURES = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}
READY_TIMEOUT = "15s"

Engine = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Log = Callable[[str], None]


def _engine(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False)  # noqa: S603


def _check(result: subprocess.CompletedProcess[str], what: str) -> subprocess.CompletedProcess[str]:
    if result.returncode != 0:
        raise NarrattyError(f"{what} failed: {(result.stderr or result.stdout).strip()}")
    return result


# ── what to run ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EnvironmentOptions:
    """Command-line choices about the environment."""

    disabled: bool = False
    image: str | None = None
    keep: bool = False


def resolve(environment: Environment | None, options: EnvironmentOptions) -> Environment | None:
    """The spec's environment with command-line overrides applied."""
    if options.disabled:
        return None
    if options.image is None:
        return environment
    base = environment.model_dump(exclude=set(ENV_SOURCES)) if environment else {}
    return Environment.model_validate({**base, "image": options.image})


def check_policy(environment: Environment, allowed: Sequence[str] | None) -> None:
    """Fail when the user's policy does not allow this kind of environment."""
    if allowed is not None and environment.source not in allowed:
        from narratty.config import config_dir

        raise UsageError(
            f"the spec runs the demo in an environment from {environment.source!r}, "
            "which your policy does not allow",
            hint=f"Pass --no-env, or extend allow_environment in {config_dir() / 'config.toml'}.",
        )


# ── images ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImageInfo:
    """What narratty needs to know about the environment's image."""

    ref: str
    id: str
    architecture: str
    user: str = ""
    env: dict[str, str] = field(default_factory=dict)

    @property
    def home(self) -> str:
        """The image user's home directory, as far as the image tells."""
        if home := self.env.get("HOME"):
            return home
        return "/root" if self.user in ("", "root", "0") or self.user.startswith("0:") else "/"


def inspect_image(engine: str, ref: str, *, run: Engine = _engine, log: Log | None = None) -> ImageInfo:
    """Inspect ``ref``, pulling it first when it is not there."""
    result = run([engine, "image", "inspect", ref])
    if result.returncode != 0:
        if log:
            log(f"pulling {ref}")
        _check(run([engine, "pull", ref]), f"pulling {ref}")
        result = _check(run([engine, "image", "inspect", ref]), f"inspecting {ref}")
    data = json.loads(result.stdout)[0]
    config = data.get("Config") or {}
    architecture = str(data.get("Architecture", ""))
    if architecture not in ARCHITECTURES:
        raise UsageError(
            f"{ref} is a {architecture or 'unknown'} image; environments need amd64 or arm64 Linux images"
        )
    env = dict(entry.partition("=")[::2] for entry in config.get("Env") or [])
    return ImageInfo(ref, str(data["Id"]), ARCHITECTURES[architecture], str(config.get("User") or ""), env)


def agent_dir(
    engine: str,
    narratty_image: str,
    architecture: str,
    *,
    cache: Path,
    run: Engine = _engine,
    env: dict[str, str] | None = None,
) -> Path:
    """Directory holding the static agent for ``architecture``.

    Copied once per narratty image from ``/opt/narratty/agent``;
    ``NARRATTY_AGENT_DIR`` points at a local build instead (``<dir>/<arch>/narratty-agent``).
    """
    environ = os.environ if env is None else env
    if override := environ.get("NARRATTY_AGENT_DIR"):
        root = Path(override).expanduser()
    else:
        image_id = _check(
            run([engine, "image", "inspect", "--format", "{{.Id}}", narratty_image]),
            f"inspecting {narratty_image}",
        ).stdout.strip()
        root = cache / "agent" / image_id.removeprefix("sha256:")[:16]
        if not root.is_dir():
            _extract(engine, narratty_image, IMAGE_AGENT_DIR, root, run)
    directory = root / architecture
    if not (directory / "narratty-agent").is_file():
        raise MissingDependencyError(
            f"no narratty-agent for {architecture} in {root}",
            hint="Use a narratty image from 0.3 on (--image), or build the agent (see agent/README.md).",
        )
    return directory


def _extract(engine: str, image: str, source: str, dest: Path, run: Engine) -> None:
    name = f"narratty-extract-{uuid.uuid4().hex[:12]}"
    partial = dest.with_name(dest.name + f".{name}")
    _check(run([engine, "create", "--name", name, image]), f"reading {image}")
    try:
        partial.mkdir(parents=True)
        _check(run([engine, "cp", f"{name}:{source}/.", str(partial)]), f"copying {source} from {image}")
        partial.rename(dest)
    finally:
        run([engine, "rm", "--force", name])
        if partial.exists():
            import shutil

            shutil.rmtree(partial, ignore_errors=True)


# ── the running environment ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Session:
    """A running environment container."""

    engine: str
    container: str
    workdir: str
    volume: str | None = None

    def exec_bridge(self) -> list[str]:
        """The bridge on the host: ``docker exec -it``."""
        return [
            self.engine, "exec", "--interactive", "--tty", "--workdir", self.workdir,
            "--env", "TERM", "--env", "COLORTERM", self.container,
        ]  # fmt: skip

    def agent_bridge(self) -> list[str]:
        """The bridge in the narratty container (with the volume at ``RECORDER_RUN_DIR``)."""
        return [RECORDER_AGENT, "connect", "--socket", f"{RECORDER_RUN_DIR}/agent.sock", "--"]

    def recorder_volume(self) -> str:
        """``--volume`` value giving the narratty container the agent's socket."""
        if self.volume is None:
            raise AssertionError("the environment was started without the agent")
        return f"{self.volume}:{RECORDER_RUN_DIR}"


def _user_flags(engine: str, user: str) -> list[str]:
    if user == "image":
        return []
    if user != "host":
        return ["--user", user]
    if engine == "podman":
        return ["--userns", "keep-id"]
    if hasattr(os, "getuid"):
        return ["--user", f"{os.getuid()}:{os.getgid()}"]
    return []  # pragma: no cover - Windows


def home_for(environment: Environment, image: ImageInfo) -> str:
    """``$HOME`` in the environment (what ``~`` in mounts means)."""
    return HOST_HOME if environment.user == "host" else image.home


def run_argv(
    environment: Environment,
    image: ImageInfo,
    *,
    engine: str,
    name: str,
    shell: str,
    workspace: PreparedWorkspace,
    access: ContainerAccess,
    network: str,
    agent: Path | None,
    volume: str | None,
    keep: bool,
) -> list[str]:
    """``run`` command for the environment's container.

    The container idles in an interactive ``shell`` (it only has to stay up); demo
    shells are started next to it with ``exec``.
    """
    argv = [
        engine, "run", "--detach", "--interactive", "--tty", "--init", "--name", name,
        "--label", "narratty.environment=1",
        "--network", network,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        *_user_flags(engine, environment.user),
        "--workdir", environment.workdir,
        "--volume", f"{workspace.path}:{environment.workdir}" + (":ro" if workspace.read_only else ""),
    ]  # fmt: skip
    if not keep:
        argv.append("--rm")
    if environment.read_only:
        argv += ["--read-only", "--tmpfs", "/tmp:rw,exec,mode=1777"]
    if environment.user == "host":
        argv += ["--tmpfs", f"{HOST_HOME}:rw,mode=1777", "--env", f"HOME={HOST_HOME}"]
    if agent is not None and volume is not None:
        argv += ["--volume", f"{agent}:{AGENT_DIR}:ro", "--volume", f"{volume}:{RUN_DIR}"]
    for mount in access.volumes:
        argv += ["--volume", mount]
    for key, value in sorted(access.env.items()):
        argv += ["--env", f"{key}={value}"]
    return [*argv, "--entrypoint", shell, image.ref]


@contextmanager
def start(
    environment: Environment,
    image: ImageInfo,
    *,
    engine: str,
    shell: str,
    workspace: PreparedWorkspace,
    access: ContainerAccess,
    network: str,
    agent: Path | None,
    keep: bool = False,
    run: Engine = _engine,
    log: Log | None = None,
) -> Iterator[Session]:
    """Start the environment; with ``agent`` (a directory), serve demo shells on a socket.

    Everything is removed afterwards unless ``keep``.
    """
    say = log or (lambda _message: None)
    name = f"narratty-env-{uuid.uuid4().hex[:12]}"
    volume = f"{name}-run" if agent is not None else None
    with ExitStack() as cleanup:
        if volume is not None:
            _check(
                run(
                    [
                        engine,
                        "volume",
                        "create",
                        "--label",
                        "narratty.environment=1",
                        "--opt",
                        "type=tmpfs",
                        "--opt",
                        "device=tmpfs",
                        "--opt",
                        "o=size=1m,mode=1777",
                        volume,
                    ]
                ),  # fmt: skip
                "creating the agent's volume",
            )
            if not keep:
                cleanup.callback(run, [engine, "volume", "rm", "--force", volume])
        say(f"starting the environment ({image.ref})")
        argv = run_argv(
            environment, image, engine=engine, name=name, shell=shell, workspace=workspace,
            access=access, network=network, agent=agent, volume=volume, keep=keep,
        )  # fmt: skip
        _check(run(argv), f"starting {image.ref}")
        if not keep:
            cleanup.callback(run, [engine, "rm", "--force", name])
        if agent is not None:
            _serve(engine, name, environment.workdir, run)
        yield Session(engine, name, environment.workdir, volume)
        if keep:
            say(f"kept the environment: {engine} exec -it {name} {shell}; remove it: {engine} rm -f {name}")


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
    run: Engine = _engine,
    log: Log | None = None,
) -> Iterator[Session]:
    """Start ``environment`` for ``spec`` under the (already approved) ``sandbox`` rules.

    ``narratty_image`` supplies the agent (``with_agent``) and the allowlist forwarders.
    """
    from narratty.paths import cache_dir
    from narratty.sandbox import allowlist_network, container_access

    if environment.image is None:
        raise AssertionError(environment)
    image = inspect_image(engine, environment.image, run=run, log=log)
    access = container_access(
        sandbox,
        spec_dir=spec_dir,
        caches=spec.workspace.caches,
        cache_root=cache_dir(),
        home=home_for(environment, image),
    )
    agent = (
        agent_dir(engine, narratty_image, image.architecture, cache=cache_dir(), run=run)
        if with_agent
        else None
    )
    launch = partial(
        start, environment, image, engine=engine, shell=spec.terminal.shell, workspace=workspace,
        access=access, agent=agent, keep=keep, run=run, log=log,
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


def _serve(engine: str, container: str, workdir: str, run: Engine) -> None:
    serve = [AGENT, "serve", "--socket", SOCKET, "--workdir", workdir]
    _check(run([engine, "exec", "--detach", container, *serve]), "starting narratty-agent")
    ping = run([engine, "exec", container, AGENT, "ping", "--socket", SOCKET, "--wait", READY_TIMEOUT])
    if ping.returncode != 0:
        logs = run([engine, "logs", container])
        raise NarrattyError(
            f"narratty-agent did not start in the environment: {(ping.stderr or ping.stdout).strip()}",
            hint=(logs.stdout + logs.stderr).strip()[-500:] or None,
        )
