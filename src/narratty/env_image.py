"""The environment's image: pulled or built from the project's Dockerfile, plus a layer
with the demo's ``packages`` and ``setup`` commands.

The layer is built from a generated Dockerfile. It runs as root only while building,
then switches back to the image's own user, and is tagged ``narratty-env:<hash>`` of
the base image id, the package manager, the packages and the setup commands, so an
unchanged spec builds nothing.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from narratty.errors import NarrattyError, UsageError
from narratty.spec.model import PACKAGE_MANAGERS, EnvBuild, Environment

Engine = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Log = Callable[[str], None]

# Install and clean up in one layer, without prompts or recommended extras.
INSTALL = {
    "apt": "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {p}"
    " && rm -rf /var/lib/apt/lists/*",
    "apk": "apk add --no-cache {p}",
    "dnf": "dnf install -y --setopt=install_weak_deps=False {p} && dnf clean all",
    "microdnf": "microdnf install -y {p} && microdnf clean all",
    "yum": "yum install -y {p} && yum clean all",
    "zypper": "zypper --non-interactive install --no-recommends {p} && zypper clean --all",
}
_DETECT = (
    "for m in apt-get apk dnf microdnf yum zypper; do "
    "if command -v $m >/dev/null 2>&1; then echo $m; exit 0; fi; done; exit 1"
)


def _tail(result: subprocess.CompletedProcess[str], lines: int = 15) -> str:
    return "\n".join((result.stderr or result.stdout or "").strip().splitlines()[-lines:])


def build_project_image(
    build: EnvBuild,
    *,
    spec_dir: Path,
    engine: str,
    run: Engine,
    rebuild: bool = False,
    log: Log | None = None,
) -> str:
    """Build the project's Dockerfile; returns the image tag (stable per context and file)."""
    context = (spec_dir / build.context).resolve()
    dockerfile = (spec_dir / build.dockerfile).resolve() if build.dockerfile else context / "Dockerfile"
    if not dockerfile.is_file():
        raise UsageError(f"environment.build: {dockerfile} does not exist")
    key = hashlib.sha256(f"{context}\0{dockerfile}\0{build.target}".encode()).hexdigest()[:12]
    tag = f"narratty-build:{key}"
    argv = [engine, "build", "--tag", tag, "--file", str(dockerfile)]
    if build.target:
        argv += ["--target", build.target]
    for name, value in sorted(build.args.items()):
        argv += ["--build-arg", f"{name}={value}"]
    if rebuild:
        argv.append("--no-cache")
    if log:
        log(f"building the environment from {dockerfile.name}")
    result = run([*argv, str(context)])
    if result.returncode != 0:
        raise NarrattyError(f"building {dockerfile} failed:\n{_tail(result)}")
    return tag


def detect_package_manager(engine: str, ref: str, image_id: str, *, cache: Path, run: Engine) -> str:
    """The package manager in ``ref``, remembered per image id."""
    store = cache / "env-package-managers.json"
    try:
        known: dict[str, str] = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    if image_id in known:
        return known[image_id]
    result = run([engine, "run", "--rm", "--network", "none", "--entrypoint", "sh", ref, "-c", _DETECT])
    found = result.stdout.strip().removesuffix("-get")
    if result.returncode != 0 or found not in PACKAGE_MANAGERS:
        raise UsageError(
            f"{ref} has no package manager narratty knows ({', '.join(PACKAGE_MANAGERS)})",
            hint="Set environment.package_manager, install tools with environment.setup, "
            "or use environment.build with your own Dockerfile.",
        )
    known[image_id] = found
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(known, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return found


def layer_dockerfile(
    base: str, user: str, manager: str | None, packages: Sequence[str], setup: Sequence[str]
) -> str:
    """The generated Dockerfile adding ``packages`` and ``setup`` to ``base``."""
    lines = [f"FROM {base}", "USER root"]
    if packages and manager:
        lines.append("RUN " + INSTALL[manager].format(p=" ".join(shlex.quote(p) for p in packages)))
    lines += [f"RUN {command}" for command in setup]
    if user:
        lines.append(f"USER {user}")
    return "\n".join(lines) + "\n"


def layer_tag(base_id: str, manager: str | None, packages: Sequence[str], setup: Sequence[str]) -> str:
    """``narratty-env:<hash>`` of everything that goes into the layer."""
    blob = json.dumps([base_id, manager, list(packages), list(setup)])
    return f"narratty-env:{hashlib.sha256(blob.encode()).hexdigest()[:16]}"


def build_layer(
    environment: Environment,
    base: str,
    base_id: str,
    base_user: str,
    *,
    engine: str,
    cache: Path,
    run: Engine,
    rebuild: bool = False,
    log: Log | None = None,
) -> str:
    """Tag of ``base`` with the environment's packages and setup (built when missing)."""
    manager: str | None = None
    if environment.packages:
        manager = environment.package_manager
        if manager == "auto":
            manager = detect_package_manager(engine, base, base_id, cache=cache, run=run)
    tag = layer_tag(base_id, manager, environment.packages, environment.setup)
    if not rebuild and run([engine, "image", "inspect", "--format", "{{.Id}}", tag]).returncode == 0:
        return tag
    if log:
        log(f"adding {', '.join(environment.packages) or 'setup commands'} to the environment")
    dockerfile = layer_dockerfile(base, base_user, manager, environment.packages, environment.setup)
    with tempfile.TemporaryDirectory(prefix="narratty-env-") as context:
        (Path(context) / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        result = run([engine, "build", "--tag", tag, context])
    if result.returncode != 0:
        raise NarrattyError(f"adding packages to {base} failed:\n{_tail(result)}", hint=dockerfile)
    return tag


def grants(environment: Environment) -> list[str]:
    """What building the environment needs approval for (root and network while building)."""
    if not environment.layered:
        return []
    parts = []
    if environment.packages:
        parts.append(f"installs {', '.join(environment.packages)}")
    if environment.setup:
        count = len(environment.setup)
        parts.append(f"runs {count} setup command{'s' if count > 1 else ''}")
    return [f"building the environment as root with network access: {' and '.join(parts)}"]
