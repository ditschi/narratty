"""Result types shared by the checks, the scoring and the reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Smell:
    """One finding: which smell, where, how bad and what it costs."""

    kind: str
    line: int
    symbol: str
    value: float
    message: str
    deduction: float = 0.0

    def to_json(self) -> dict[str, Any]:
        """Plain dict for ``--json``."""
        return asdict(self)


@dataclass
class FileReport:
    """Score of one file and the smells behind it."""

    path: str
    loc: int
    score: float = 10.0
    smells: list[Smell] = field(default_factory=list)
    suppressed: list[Smell] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """Plain dict for ``--json``."""
        return {
            "path": self.path,
            "score": self.score,
            "loc": self.loc,
            "smells": [smell.to_json() for smell in self.smells],
            "suppressed": [smell.to_json() for smell in self.suppressed],
        }
