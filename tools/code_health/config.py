"""Load the versioned thresholds and weights from ``code-health.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILE = "code-health.toml"


@dataclass(frozen=True)
class Rule:
    """One smell's settings: where it starts and what one occurrence costs."""

    threshold: float = 0.0
    weight: float = 0.0
    step: float = 0.0
    max: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def deduction(self, value: float) -> float:
        """Cost of one occurrence with the measured ``value`` (at or above the threshold)."""
        cost = self.weight + self.step * max(0.0, value - self.threshold)
        return round(min(cost, self.max) if self.max else cost, 3)

    def __getitem__(self, key: str) -> Any:
        return self.extra[key]


@dataclass(frozen=True)
class Config:
    """The whole configuration file."""

    root: Path
    version: int
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    test_globs: tuple[str, ...]
    min_file_score: float
    baseline: Path
    category_cap: float
    min_score: float
    rules: dict[str, Rule]

    def rule(self, smell: str) -> Rule:
        """Settings of ``smell``."""
        return self.rules[smell]


_RULE_KEYS = {"threshold", "weight", "step", "max"}


def _rule(raw: dict[str, Any]) -> Rule:
    known = {key: float(value) for key, value in raw.items() if key in _RULE_KEYS}
    extra = {key: value for key, value in raw.items() if key not in _RULE_KEYS}
    return Rule(**known, extra=extra)


def load(root: Path) -> Config:
    """Read ``code-health.toml`` from the repository ``root``."""
    data = tomllib.loads((root / CONFIG_FILE).read_text(encoding="utf-8"))
    gate, score = data["gate"], data["score"]
    return Config(
        root=root,
        version=int(data["version"]),
        include=tuple(data["include"]),
        exclude=tuple(data.get("exclude", ())),
        test_globs=tuple(data.get("test_globs", ())),
        min_file_score=float(gate["min_file_score"]),
        baseline=root / gate["baseline"],
        category_cap=float(score["category_cap"]),
        min_score=float(score["min_score"]),
        rules={name: _rule(raw) for name, raw in data["smells"].items()},
    )
