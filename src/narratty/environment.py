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

import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from narratty.errors import MissingDependencyError, NarrattyError, UsageError
from narratty.spec.model import ENV_SOURCES, Environment

if TYPE_CHECKING:
    from narratty.sandbox import ContainerAccess, Policy
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
    rebuild: bool = False


def resolve(environment: Environment | None, options: EnvironmentOptions) -> Environment | None:
    """The spec's environment with command-line overrides applied."""
    if options.disabled:
        return None
    if options.image is None:
        return environment
    base = environment.model_dump(exclude=set(ENV_SOURCES)) if environment else {}
    return Environment.model_validate({**base, "image": options.image})


def check_policy(environment: Environment, policy: Policy) -> None:
    """Fail when the user's policy does not allow this environment."""
    from narratty.config import config_dir

    where = f"{config_dir() / 'config.toml'}"
    allowed = policy.allow_environment
    if allowed is not None and environment.source not in allowed:
        raise UsageError(
            f"the spec runs the demo in an environment from {environment.source!r}, "
            "which your policy does not allow",
            hint=f"Pass --no-env, or extend allow_environment in {where}.",
        )
    if environment.layered and not policy.allow_packages:
        raise UsageError(
            "the spec adds packages or setup commands to its environment, which your policy does not allow",
            hint=f"Pass --no-env, or set allow_packages = true in {where}.",
        )


# ── images ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImageInfo:
    """What narratty needs to know about the environment's image."""

    ref: str
    id: str  # of the content, see inspect_image
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
    # The image's content (layers and config). The Id is no cache key: with the containerd
    # image store it covers attestations, which change on every otherwise cached build.
    content = json.dumps([data.get("RootFS"), config, architecture], sort_keys=True)
    image_id = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
    return ImageInfo(ref, image_id, ARCHITECTURES[architecture], str(config.get("User") or ""), env)


def prepare_image(
    environment: Environment,
    *,
    spec_dir: Path,
    engine: str,
    rebuild: bool = False,
    run: Engine = _engine,
    log: Log | None = None,
) -> ImageInfo:
    """Pull the environment's image, and add its packages and setup."""
    from narratty.env_image import build_layer
    from narratty.paths import cache_dir

    if environment.image is None:
        raise AssertionError(environment)
    ref = environment.image
    image = inspect_image(engine, ref, run=run, log=log)
    if not environment.layered:
        return image
    tag = build_layer(
        environment,
        ref,
        image.id,
        image.user,
        engine=engine,
        cache=cache_dir(),
        run=run,
        rebuild=rebuild,
        log=log,
    )
    return inspect_image(engine, tag, run=run, log=log)


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
    """A running environment container and how to reach its shell."""

    engine: str
    container: str
    workdir: str | None = None
    volume: str | None = None  # holds the agent's socket (image, compose)
    socket: str | None = None  # an abstract socket in the container's network (container)
    user: str | None = None  # for exec, when the container runs as someone else

    def exec_bridge(self) -> list[str]:
        """The bridge on the host: ``docker exec -it``."""
        argv = [self.engine, "exec", "--interactive", "--tty", "--env", "TERM", "--env", "COLORTERM"]
        if self.workdir:
            argv += ["--workdir", self.workdir]
        if self.user:
            argv += ["--user", self.user]
        return [*argv, self.container]

    def agent_bridge(self) -> list[str]:
        """The bridge in the narratty container (given :meth:`recorder_flags`)."""
        socket = self.socket or f"{RECORDER_RUN_DIR}/agent.sock"
        return [RECORDER_AGENT, "connect", "--socket", socket, "--"]

    def recorder_flags(self) -> tuple[list[str], str | None]:
        """Volumes and network the narratty container needs to reach the agent."""
        if self.socket is not None:
            return [], f"container:{self.container}"
        if self.volume is None:
            raise UsageError(
                f"the environment {self.container} was started without narratty-agent",
                hint="Remove it with `narratty env down`, then start it with a container runtime.",
            )
        return [f"{self.volume}:{RECORDER_RUN_DIR}"], None


def user_flags(engine: str, user: str) -> list[str]:
    """``run`` flags for ``environment.user``."""
    if user == "image":
        return []
    if user != "host":
        return ["--user", user]
    if engine == "podman":
        return ["--userns", "keep-id"]
    return ["--user", host_user()]


def host_user() -> str:
    """``UID:GID`` of the current user."""
    if hasattr(os, "getuid"):
        return f"{os.getuid()}:{os.getgid()}"
    return "1000:1000"  # pragma: no cover - Windows


def home_for(environment: Environment, image: ImageInfo) -> str:
    """``$HOME`` in the environment (what ``~`` in mounts means)."""
    return HOST_HOME if environment.user == "host" else image.home


def spec_key(spec_path: Path) -> str:
    """Identifies a spec file in container names and labels."""
    return hashlib.sha256(str(spec_path.resolve()).encode()).hexdigest()[:12]


def create_run_volume(engine: str, name: str, run: Engine) -> None:
    """A small tmpfs volume for the agent's socket, shared with the narratty container."""
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
                name,
            ]
        ),  # fmt: skip
        "creating the agent's volume",
    )


@dataclass
class Mounts:
    """What goes into the environment besides the workspace."""

    access: ContainerAccess
    agent: Path | None = None
    volume: str | None = None
    toolkit: Path | None = None
    labels: dict[str, str] = field(default_factory=dict)

    def volumes(self) -> list[str]:
        """``--volume`` values."""
        volumes = list(self.access.volumes)
        if self.agent is not None and self.volume is not None:
            volumes += [f"{self.agent}:{AGENT_DIR}:ro", f"{self.volume}:{RUN_DIR}"]
        if self.toolkit is not None:
            from narratty.env_toolkit import TOOLKIT_DIR

            volumes.append(f"{self.toolkit}:{TOOLKIT_DIR}:ro")
        return volumes


def run_argv(
    environment: Environment,
    image: ImageInfo,
    *,
    engine: str,
    name: str,
    shell: str,
    workspace: PreparedWorkspace,
    mounts: Mounts,
    network: str,
    keep: bool,
) -> list[str]:
    """``run`` command for an image environment.

    The container idles in an interactive ``shell`` (it only has to stay up); demo
    shells are started next to it with ``exec``.
    """
    workdir = environment.mount_point
    argv = [
        engine, "run", "--detach", "--interactive", "--tty", "--init", "--name", name,
        "--label", "narratty.environment=1",
        "--network", network,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        *user_flags(engine, environment.user),
        "--workdir", workdir,
        "--volume", f"{workspace.path}:{workdir}" + (":ro" if workspace.read_only else ""),
    ]  # fmt: skip
    if not keep:
        argv.append("--rm")
    if environment.read_only:
        argv += ["--read-only", "--tmpfs", "/tmp:rw,exec,mode=1777"]
    if environment.user == "host":
        argv += ["--tmpfs", f"{HOST_HOME}:rw,mode=1777", "--env", f"HOME={HOST_HOME}"]
    for key, value in sorted(mounts.labels.items()):
        argv += ["--label", f"{key}={value}"]
    for volume in mounts.volumes():
        argv += ["--volume", volume]
    for key, value in sorted(mounts.access.env.items()):
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
    mounts: Mounts,
    network: str,
    name: str | None = None,
    keep: bool = False,
    run: Engine = _engine,
    log: Log | None = None,
) -> Iterator[Session]:
    """Start an image environment; with an agent, serve demo shells on a socket.

    Everything is removed afterwards unless ``keep``.
    """
    say = log or (lambda _message: None)
    name = name or f"narratty-env-{uuid.uuid4().hex[:12]}"
    with ExitStack() as cleanup:
        if mounts.agent is not None:
            mounts.volume = f"{name}-run"
            mounts.labels["narratty.volume"] = mounts.volume
            create_run_volume(engine, mounts.volume, run)
            if not keep:
                cleanup.callback(run, [engine, "volume", "rm", "--force", mounts.volume])
        mounts.labels["narratty.workdir"] = environment.mount_point
        say(f"starting the environment ({image.ref})")
        argv = run_argv(
            environment, image, engine=engine, name=name, shell=shell, workspace=workspace,
            mounts=mounts, network=network, keep=keep,
        )  # fmt: skip
        result = run(argv)
        if result.returncode != 0:
            raise NarrattyError(
                f"starting {image.ref} failed: {(result.stderr or result.stdout).strip()}",
                hint=f"The image needs Linux and `{shell}` (terminal.shell).",
            )
        if not keep:
            cleanup.callback(run, [engine, "rm", "--force", name])
        if mounts.agent is not None:
            serve_agent(engine, name, AGENT, SOCKET, environment.mount_point, run=run)
        yield Session(engine, name, environment.mount_point, mounts.volume)
        if keep:
            say(f"kept the environment {name}; remove it with `narratty env down` or `{engine} rm -f {name}`")


def add_toolkit(
    environment: Environment, image: ImageInfo, mounts: Mounts, *, engine: str, run: Engine, log: Log | None
) -> None:
    """Mount the demo toolkit (unless ``toolkit: off``) and put it on ``PATH``."""
    from narratty.env_toolkit import toolkit_dir, toolkit_env
    from narratty.paths import cache_dir

    if environment.toolkit == "off":
        return
    mounts.toolkit = toolkit_dir(engine, image.architecture, cache=cache_dir(), run=run, log=log)
    if mounts.toolkit is not None:
        mounts.access.env.update(toolkit_env(environment.toolkit, image.env.get("PATH")))


def serve_agent(
    engine: str,
    container: str,
    agent: str,
    socket: str,
    workdir: str | None,
    *,
    user: str | None = None,
    once: bool = False,
    run: Engine = _engine,
) -> None:
    """Start ``agent serve`` in ``container`` and wait until it answers."""
    serve = [agent, "serve", "--socket", socket]
    if workdir:
        serve += ["--workdir", workdir]
    if once:
        serve.append("--once")
    as_user = ["--user", user] if user else []
    _check(run([engine, "exec", "--detach", *as_user, container, *serve]), "starting narratty-agent")
    ping = run([engine, "exec", container, agent, "ping", "--socket", socket, "--wait", READY_TIMEOUT])
    if ping.returncode != 0:
        logs = run([engine, "logs", container])
        raise NarrattyError(
            f"narratty-agent did not start in the environment: {(ping.stderr or ping.stdout).strip()}",
            hint=(logs.stdout + logs.stderr).strip()[-500:] or None,
        )


# ── environments kept for later runs (env up / down) ──────────────────────────


def running(engine: str, spec_path: Path, *, run: Engine = _engine) -> tuple[Session, Path] | None:
    """The environment ``env up`` started for ``spec_path``, and its workspace."""
    key = spec_key(spec_path)
    found = run([engine, "ps", "--format", "{{.Names}}", "--filter", f"label=narratty.spec={key}"])
    container = next(iter(found.stdout.split()), None) if found.returncode == 0 else None
    if container is None:
        return None
    inspect = [engine, "inspect", "--format", "{{json .Config.Labels}}", container]
    labels = json.loads(_check(run(inspect), "inspecting the environment").stdout or "{}") or {}
    session = Session(
        engine,
        container,
        labels.get("narratty.workdir") or None,
        labels.get("narratty.volume") or None,
        user=labels.get("narratty.user") or None,
    )
    return session, Path(labels["narratty.workspace"])


def down(engine: str, spec_path: Path, *, run: Engine = _engine, log: Log | None = None) -> int:
    """Remove every environment kept for ``spec_path``; returns how many."""
    import shutil

    key = spec_key(spec_path)
    found = run([engine, "ps", "--all", "--quiet", "--filter", f"label=narratty.spec={key}"])
    containers = found.stdout.split() if found.returncode == 0 else []
    for container in containers:
        labels = json.loads(
            run([engine, "inspect", "--format", "{{json .Config.Labels}}", container]).stdout or "{}"
        ) or {}  # fmt: skip
        if project := labels.get("com.docker.compose.project"):
            run([engine, "compose", "--project-name", project, "down", "--volumes", "--remove-orphans"])
        else:
            run([engine, "rm", "--force", container])
        if volume := labels.get("narratty.volume"):
            run([engine, "volume", "rm", "--force", volume])
        if snapshot := labels.get("narratty.snapshot"):
            shutil.rmtree(snapshot, ignore_errors=True)
        if log:
            log(f"removed {labels.get('narratty.name', container)}")
    return len(containers)
