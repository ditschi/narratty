"""Typed exception hierarchy mapped to stable process exit codes.

Exit-code contract:
    0  ok
    1  generic / unexpected error
    2  usage error (also what Click uses for bad arguments)
    3  spec validation error
    4  missing dependency (tool, voice, container runtime)
    5  render or mux failure
    6  sync verification failure
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable process exit codes. Do not renumber."""

    OK = 0
    GENERIC = 1
    USAGE = 2
    VALIDATION = 3
    MISSING_DEPENDENCY = 4
    RENDER = 5
    SYNC = 6


class NarrattyError(Exception):
    """Base class for all narratty errors.

    Carries an :class:`ExitCode` plus an optional user-facing ``hint`` that the
    UI layer renders as a "next step" line.
    """

    exit_code: ExitCode = ExitCode.GENERIC

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(NarrattyError):
    """Invalid invocation or arguments."""

    exit_code = ExitCode.USAGE


class ValidationError(NarrattyError):
    """The spec is well-formed but refers to something that does not exist (e.g. a voice)."""

    exit_code = ExitCode.VALIDATION


class MissingDependencyError(NarrattyError):
    """A required tool, voice or container runtime is not available."""

    exit_code = ExitCode.MISSING_DEPENDENCY


class RenderError(NarrattyError):
    """Synthesis, rendering or muxing failed."""

    exit_code = ExitCode.RENDER


class SyncError(NarrattyError):
    """The rendered video drifted too far from the timeline."""

    exit_code = ExitCode.SYNC
