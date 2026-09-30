"""Sandbox permissions: CLI overrides, the user's policy cap, consent and the
container flags that implement them.

A spec's ``sandbox`` block says what the demo needs. The user stays in control:
``--network`` / ``--allow-host`` override it, ``~/.config/narratty/config.toml`` caps
it, and anything beyond the locked-down default needs a one-time approval that is
remembered per spec path and sandbox contents.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from narratty.config import config_dir, config_file, config_section
from narratty.errors import NarrattyError, UsageError
from narratty.spec.model import Sandbox

NETWORK_LEVELS = ("none", "allowlist", "full")
CONTAINER_HOME = "/home/narratty"


@dataclass(frozen=True)
class Policy:
    """The user's cap on what any spec may get (``[sandbox]`` in config.toml)."""

    max_network: str = "full"
    allow_env: tuple[str, ...] | None = None  # None = any name
    allow_mounts: bool = True
    allow_ssh_agent: bool = True
    allow_environment: tuple[str, ...] | None = None  # None = any source


def load_policy(directory: Path | None = None) -> Policy:
    """Read the policy; a missing file means no cap."""
    path = config_file(directory)
    raw = config_section("sandbox", directory)
    max_network = raw.get("max_network", "full")
    if max_network not in NETWORK_LEVELS:
        raise UsageError(f"{path}: max_network must be one of {', '.join(NETWORK_LEVELS)}")
    allow_env = raw.get("allow_env")
    allow_environment = raw.get("allow_environment")
    return Policy(
        max_network=max_network,
        allow_env=tuple(allow_env) if allow_env is not None else None,
        allow_mounts=bool(raw.get("allow_mounts", True)),
        allow_ssh_agent=bool(raw.get("allow_ssh_agent", True)),
        allow_environment=tuple(allow_environment) if allow_environment is not None else None,
    )


def apply_overrides(
    sandbox: Sandbox, *, network: str | None = None, allow_hosts: Sequence[str] = ()
) -> Sandbox:
    """The spec's sandbox with command-line overrides applied (and re-validated)."""
    if network is None and not allow_hosts:
        return sandbox
    data = sandbox.model_dump()
    if allow_hosts:
        data["allow_hosts"] = sorted({*data["allow_hosts"], *allow_hosts})
        data["network"] = network or "allowlist"
    elif network is not None:
        data["network"] = network
        if network != "allowlist":
            data["allow_hosts"] = []
    try:
        return Sandbox.model_validate(data)
    except ValueError as error:
        raise UsageError(f"invalid sandbox override: {error}") from error


def check_policy(sandbox: Sandbox, policy: Policy) -> None:
    """Fail when the sandbox asks for more than the user's policy allows."""
    problems: list[str] = []
    if NETWORK_LEVELS.index(sandbox.network) > NETWORK_LEVELS.index(policy.max_network):
        problems.append(f"network: {sandbox.network} (your policy allows up to {policy.max_network})")
    if policy.allow_env is not None:
        denied = sorted(set(sandbox.env_passthrough) - set(policy.allow_env))
        if denied:
            problems.append(f"env_passthrough {', '.join(denied)} (not in your policy's allow_env)")
    if sandbox.extra_mounts and not policy.allow_mounts:
        problems.append("extra_mounts (your policy sets allow_mounts = false)")
    if sandbox.ssh_agent and not policy.allow_ssh_agent:
        problems.append("ssh_agent (your policy sets allow_ssh_agent = false)")
    if problems:
        raise UsageError(
            "the spec's sandbox needs more than your policy allows: " + "; ".join(problems),
            hint=f"Adjust the spec, or the [sandbox] section of {config_dir() / 'config.toml'}.",
        )


def describe(sandbox: Sandbox) -> list[str]:
    """Human-readable list of what the sandbox grants beyond the default."""
    lines: list[str] = []
    if sandbox.network == "full":
        lines.append("full network access")
    elif sandbox.network == "allowlist":
        lines.append(f"network access to {', '.join(sandbox.allow_hosts)}")
    if sandbox.env_passthrough:
        lines.append(f"your environment variables {', '.join(sandbox.env_passthrough)}")
    for mount in sandbox.extra_mounts:
        lines.append(f"{mount.host} mounted at {mount.container} ({mount.mode})")
    if sandbox.ssh_agent:
        lines.append("your SSH agent")
    return lines


def approval_key(spec_path: Path, sandbox: Sandbox) -> str:
    """Identifies one spec file with one exact sandbox block."""
    blob = json.dumps([str(spec_path.resolve()), sandbox.model_dump(mode="json")], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


Confirm = Callable[[str], bool]


def ensure_consent(
    spec_path: Path,
    sandbox: Sandbox,
    *,
    assume_yes: bool = False,
    interactive: bool = True,
    confirm: Confirm | None = None,
    directory: Path | None = None,
) -> None:
    """Ask once before granting more than the default; remember the answer."""
    if not sandbox.elevated:
        return
    store = (directory or config_dir()) / "approvals.json"
    try:
        approved: dict[str, str] = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        approved = {}
    key = approval_key(spec_path, sandbox)
    if key in approved:
        return
    grants = describe(sandbox)
    if not assume_yes:
        if not interactive or confirm is None:
            raise UsageError(
                f"{spec_path} asks for: {'; '.join(grants)}",
                hint="Run it once in a terminal to approve, or pass --yes (e.g. in CI).",
            )
        question = f"{spec_path.name} asks for:\n  - " + "\n  - ".join(grants) + "\nAllow this?"
        if not confirm(question):
            raise UsageError("sandbox permissions were not approved")
    approved[key] = str(spec_path.resolve())
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(approved, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass
class ContainerAccess:
    """Extra ``run`` flags derived from the sandbox."""

    network: str = "none"
    flags: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    volumes: list[str] = field(default_factory=list)


def _container_path(path: str, home: str = CONTAINER_HOME) -> str:
    return home.rstrip("/") + path[1:] if path.startswith("~") else path


def container_access(
    sandbox: Sandbox,
    *,
    spec_dir: Path,
    caches: Mapping[str, str],
    cache_root: Path,
    environ: Mapping[str, str] | None = None,
    home: str = CONTAINER_HOME,
) -> ContainerAccess:
    """Flags for everything but the allowlist network (see :func:`allowlist_network`).

    ``~`` in container paths means ``home``.
    """
    environ = os.environ if environ is None else environ
    access = ContainerAccess(network="none" if sandbox.network == "none" else "bridge")
    access.env.update(sandbox.env)
    for name in sandbox.env_passthrough:
        if name in environ:
            access.env[name] = environ[name]
    for mount in sandbox.extra_mounts:
        host = (spec_dir / Path(mount.host).expanduser()).resolve()
        if not host.exists():
            raise UsageError(f"extra mount {mount.host} does not exist", hint=f"Resolved to {host}.")
        suffix = ":ro" if mount.mode == "ro" else ""
        access.volumes.append(f"{host}:{_container_path(mount.container, home)}{suffix}")
    for name, path in sorted(caches.items()):
        host = cache_root / "build-caches" / name
        host.mkdir(parents=True, exist_ok=True)
        access.volumes.append(f"{host}:{_container_path(path, home)}")
    if sandbox.ssh_agent:
        sock = environ.get("SSH_AUTH_SOCK")
        if not sock:
            raise UsageError(
                "sandbox.ssh_agent is set but SSH_AUTH_SOCK is not", hint="Start an ssh-agent first."
            )
        access.volumes.append(f"{sock}:/run/ssh-agent.sock")
        access.env["SSH_AUTH_SOCK"] = "/run/ssh-agent.sock"
    return access


Resolver = Callable[[str], str]
Engine = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def resolve_ipv4(host: str) -> str:
    """The host's first IPv4 address, resolved on the host."""
    try:
        return str(socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0])
    except OSError as error:
        raise UsageError(f"cannot resolve allowed host {host}: {error}") from error


def _engine(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False)  # noqa: S603


def _group_hosts(allow_hosts: Sequence[str]) -> dict[str, list[int]]:
    hosts: dict[str, list[int]] = {}
    for entry in allow_hosts:
        host, _, port = entry.rpartition(":")
        hosts.setdefault(host, []).append(int(port))
    return hosts


@contextmanager
def allowlist_network(
    engine: str,
    image: str,
    allow_hosts: Sequence[str],
    *,
    resolver: Resolver = resolve_ipv4,
    run: Engine = _engine,
) -> Iterator[str]:
    """An internal network where each allowed host name resolves to a forwarder.

    One sidecar per allowed host joins the internal network under that host's name
    and forwards its ports to the real host (resolved here, on the host). Yields the
    network name; everything is removed afterwards.
    """
    name = f"narratty-{uuid.uuid4().hex[:12]}"
    sidecars: list[str] = []

    def check(result: subprocess.CompletedProcess[str], what: str) -> subprocess.CompletedProcess[str]:
        if result.returncode != 0:
            raise NarrattyError(f"{what} failed: {(result.stderr or result.stdout).strip()}")
        return result

    check(run([engine, "network", "create", "--internal", name]), "creating the sandbox network")
    try:
        for index, (host, ports) in enumerate(sorted(_group_hosts(allow_hosts).items())):
            address = resolver(host)
            sidecar = f"{name}-fwd{index}"
            rules = [f"{port}={address}:{port}" for port in sorted(set(ports))]
            check(
                run(
                    [
                        engine,
                        "run",
                        "--detach",
                        "--rm",
                        "--name",
                        sidecar,
                        "--cap-drop",
                        "ALL",
                        "--cap-add",
                        "NET_BIND_SERVICE",
                        "--security-opt",
                        "no-new-privileges",
                        "--read-only",
                        "--user",
                        "0",
                        "--entrypoint",
                        "python",
                        image,
                        "-m",
                        "narratty.forward",
                        *rules,
                    ]
                ),  # fmt: skip
                f"starting the forwarder for {host}",
            )
            sidecars.append(sidecar)
            check(run([engine, "network", "connect", "--alias", host, name, sidecar]), f"attaching {host}")
        yield name
    finally:
        for sidecar in sidecars:
            run([engine, "rm", "--force", sidecar])
        run([engine, "network", "rm", name])
