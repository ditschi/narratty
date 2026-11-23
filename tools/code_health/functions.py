"""Function smells: Complex Method, Large Method, Brain Method, nesting, Bumpy Road, ..."""

from __future__ import annotations

from .config import Config
from .metrics import FunctionMetrics
from .model import Smell

# (smell, metric attribute, what the number means)
_THRESHOLD_SMELLS = (
    ("complex_method", "cyclomatic", "cyclomatic complexity"),
    ("cognitive_complexity", "cognitive", "cognitive complexity"),
    ("large_method", "loc", "code lines"),
    ("many_arguments", "params", "parameters"),
    ("nested_complexity", "nesting", "nesting depth"),
    ("bumpy_road", "bumps", "bumps"),
)


def function_smells(metrics: FunctionMetrics, config: Config) -> list[Smell]:
    """Every smell one function has."""
    specs = [spec for spec in _THRESHOLD_SMELLS if not (spec[0] == "many_arguments" and metrics.injected)]
    smells = [smell for spec in specs if (smell := _threshold_smell(metrics, config, spec))]
    smells += _complex_conditionals(metrics, config)
    if _is_brain_method(metrics, config):
        rule = config.rule("brain_method")
        message = (
            f"brain method: {metrics.loc} lines, cyclomatic complexity {metrics.cyclomatic}, "
            f"nesting {metrics.nesting}"
        )
        smells.append(Smell("brain_method", metrics.line, metrics.name, 1, message, rule.weight))
    return smells


def _threshold_smell(metrics: FunctionMetrics, config: Config, spec: tuple[str, str, str]) -> Smell | None:
    kind, attribute, label = spec
    rule = config.rule(kind)
    value = getattr(metrics, attribute)
    if value < rule.threshold:
        return None
    message = f"{label} {value} (threshold {rule.threshold:g})"
    return Smell(kind, metrics.line, metrics.name, value, message, rule.deduction(value))


def _complex_conditionals(metrics: FunctionMetrics, config: Config) -> list[Smell]:
    rule = config.rule("complex_conditional")
    return [
        Smell(
            "complex_conditional",
            line,
            metrics.name,
            operators,
            f"condition with {operators} and/or operators (threshold {rule.threshold:g})",
            rule.deduction(operators),
        )
        for line, operators in metrics.conditions
        if operators >= rule.threshold
    ]


def _is_brain_method(metrics: FunctionMetrics, config: Config) -> bool:
    rule = config.rule("brain_method")
    return bool(
        metrics.loc >= rule["loc"]
        and metrics.cyclomatic >= rule["cyclomatic"]
        and metrics.nesting >= rule["nesting"]
    )
