"""Module smells: Large File, Many Functions, Primitive Obsession."""

from __future__ import annotations

from .config import Config
from .metrics import FunctionMetrics
from .model import Smell
from .source import Source

MODULE_SMELLS = frozenset({"large_file", "many_functions", "primitive_obsession"})


def module_smells(source: Source, functions: list[FunctionMetrics], config: Config) -> list[Smell]:
    """Findings about the file as a whole, anchored at line 1."""
    smells = [
        _over("large_file", source.loc, "code lines in the file", config),
        _over("many_functions", len(functions), "functions and methods in the file", config),
        _primitive_obsession(functions, config),
    ]
    return [smell for smell in smells if smell]


def _over(kind: str, value: int, label: str, config: Config) -> Smell | None:
    rule = config.rule(kind)
    if value < rule.threshold:
        return None
    message = f"{value} {label} (threshold {rule.threshold:g})"
    return Smell(kind, 1, "<module>", value, message, rule.deduction(value))


def _primitive_obsession(functions: list[FunctionMetrics], config: Config) -> Smell | None:
    rule = config.rule("primitive_obsession")
    annotated = sum(metrics.annotated_params for metrics in functions)
    primitive = sum(metrics.primitive_params for metrics in functions)
    if annotated < rule["min_params"] or primitive / annotated < rule["ratio"]:
        return None
    share = primitive / annotated
    message = f"{share:.0%} of {annotated} annotated parameters are str/int/float/bool/bytes"
    return Smell("primitive_obsession", 1, "<module>", round(share, 2), message, rule.weight)
