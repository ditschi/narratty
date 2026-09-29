"""Preflight checks: are the tools the chosen runtime needs available?"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from narratty.runtime import ResolvedRuntime, Runtime, Which


@dataclass(frozen=True)
class Tool:
    """An external program narratty depends on."""

    name: str
    purpose: str
    install_hint: str


@dataclass(frozen=True)
class CheckResult:
    """Outcome of looking up one tool on PATH."""

    tool: Tool
    path: str | None

    @property
    def ok(self) -> bool:
        """True when the tool was found."""
        return self.path is not None


NATIVE_TOOLS: tuple[Tool, ...] = (
    Tool("vhs", "renders the terminal session", "https://github.com/charmbracelet/vhs#installation"),
    Tool("ttyd", "terminal backend used by VHS", "apt install ttyd  |  brew install ttyd"),
    Tool("ffmpeg", "encodes and muxes video and audio", "apt install ffmpeg  |  brew install ffmpeg"),
    Tool("ffprobe", "measures narration durations", "ships with ffmpeg"),
    Tool("piper", "default text-to-speech provider", "pip install piper-tts"),
    Tool("git", "creates snapshot workspaces", "apt install git  |  brew install git"),
)

CONTAINER_TOOLS: dict[Runtime, Tool] = {
    Runtime.DOCKER: Tool("docker", "runs the sandboxed render", "https://docs.docker.com/get-docker/"),
    Runtime.PODMAN: Tool("podman", "runs the sandboxed render", "https://podman.io/docs/installation"),
}


def required_tools(resolved: ResolvedRuntime) -> tuple[Tool, ...]:
    """Tools the resolved runtime needs on the host."""
    container_tool = CONTAINER_TOOLS.get(resolved.runtime)
    if container_tool is not None:
        return (container_tool,)
    return NATIVE_TOOLS


def run_checks(resolved: ResolvedRuntime, *, which: Which | None = None) -> list[CheckResult]:
    """Look up every tool the resolved runtime needs."""
    lookup = shutil.which if which is None else which
    return [CheckResult(tool, lookup(tool.name)) for tool in required_tools(resolved)]
