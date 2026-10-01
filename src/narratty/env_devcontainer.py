"""Read a ``devcontainer.json`` into an environment (``environment.devcontainer``).

The file names an image, a Dockerfile or a Compose service; narratty runs that like
the matching ``environment`` source. ``workspaceFolder``, ``remoteUser`` (or
``containerUser``), ``containerEnv`` and ``remoteEnv`` carry over. Dev container
features and lifecycle commands need the Dev Container CLI and are skipped with a
note; prebuild such a container with ``devcontainer build --image-name NAME`` and use
``environment.image``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from narratty.errors import UsageError
from narratty.spec.model import Environment

Log = Callable[[str], None]

SKIPPED = (
    "features",
    "initializeCommand",
    "onCreateCommand",
    "updateContentCommand",
    "postCreateCommand",
    "postStartCommand",
    "postAttachCommand",
    "runArgs",
    "mounts",
    "workspaceMount",
)
_VARIABLE = re.compile(r"\$\{([^}]+)\}")


def parse_jsonc(text: str) -> Any:
    """JSON with comments and trailing commas, as devcontainer.json allows."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if char == '"':
            end = i + 1
            while end < n and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[i : end + 1])
            i = end + 1
        elif text.startswith("//", i):
            i = text.find("\n", i) if "\n" in text[i:] else n
        elif text.startswith("/*", i):
            close = text.find("*/", i + 2)
            i = n if close < 0 else close + 2
        else:
            out.append(char)
            i += 1
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    return json.loads(cleaned)


def _substitute(value: Any, variables: Mapping[str, str], env: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _substitute(item, variables, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, variables, env) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name.startswith("localEnv:"):
            key, _, default = name.removeprefix("localEnv:").partition(":")
            return env.get(key, default)
        return variables.get(name, match.group(0))

    return _VARIABLE.sub(replace, value)


def _relative(path: Path, spec_dir: Path) -> str:
    return os.path.relpath(path, spec_dir)


def _read(file: Path) -> dict[str, Any]:
    try:
        config = parse_jsonc(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UsageError(f"no devcontainer.json at {file}") from None
    except json.JSONDecodeError as error:
        raise UsageError(f"{file} is not valid JSON: {error}") from None
    if not isinstance(config, dict):
        raise UsageError(f"{file} is not a JSON object")
    return config


def _source(config: dict[str, Any], file: Path, spec_dir: Path, workspace_folder: str) -> dict[str, Any]:
    """The ``image``, ``build`` or ``compose`` entry, and the matching ``workdir``."""
    folder = file.parent
    if compose := config.get("dockerComposeFile"):
        if not config.get("service"):
            raise UsageError(f"{file} names dockerComposeFile but no service")
        files = [compose] if isinstance(compose, str) else list(compose)
        source = {
            "file": [_relative(folder / name, spec_dir) for name in files],
            "service": config["service"],
        }
        return {"compose": source, "workdir": config.get("workspaceFolder")}
    build = config.get("build") or ({"dockerfile": config["dockerFile"]} if "dockerFile" in config else None)
    if build:
        return {
            "build": {
                "context": _relative(folder / build.get("context", "."), spec_dir),
                "dockerfile": _relative(folder / build.get("dockerfile", "Dockerfile"), spec_dir),
                "target": build.get("target"),
                "args": {key: str(value) for key, value in (build.get("args") or {}).items()},
            },
            "workdir": workspace_folder,
        }
    if image := config.get("image"):
        return {"image": image, "workdir": workspace_folder}
    raise UsageError(f"{file} names no image, build or dockerComposeFile")


def expand(
    environment: Environment,
    spec_dir: Path,
    *,
    env: Mapping[str, str] | None = None,
    log: Log | None = None,
) -> Environment:
    """The environment ``environment.devcontainer`` describes (others are returned as they are).

    Keys set in the spec (``workdir``, ``user``, ``env``, ``packages``, ...) win.
    """
    if environment.devcontainer is None:
        return environment
    file = (spec_dir / environment.devcontainer).resolve()
    if file.is_dir():
        file = file / "devcontainer.json"
    config = _read(file)
    project = file.parent.parent if file.parent.name == ".devcontainer" else file.parent
    workspace_folder = config.get("workspaceFolder") or f"/workspaces/{project.name}"
    variables = {
        "localWorkspaceFolder": str(project),
        "localWorkspaceFolderBasename": project.name,
        "containerWorkspaceFolder": workspace_folder,
        "containerWorkspaceFolderBasename": Path(workspace_folder).name,
    }
    config = _substitute(config, variables, os.environ if env is None else env)
    if log and (skipped := [key for key in SKIPPED if config.get(key)]):
        log(f"{file.name}: skipping {', '.join(skipped)} (not supported; see the docs on dev containers)")

    data = {key: value for key, value in _source(config, file, spec_dir, workspace_folder).items() if value}
    data.update(environment.model_dump(exclude={"devcontainer"}, exclude_unset=True))
    data["env"] = {**config.get("containerEnv", {}), **config.get("remoteEnv", {}), **environment.env}
    user = config.get("remoteUser") or config.get("containerUser")
    if user and "user" not in environment.model_fields_set:
        data["user"] = user
    return Environment.model_validate(data)
