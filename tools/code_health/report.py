"""Render results as a readable table or as JSON for agents."""

from __future__ import annotations

import json
from typing import Any

from .gate import GateResult
from .model import FileReport, Smell


def _band(score: float) -> str:
    if score >= 9.0:
        return "green"
    return "yellow" if score >= 4.0 else "red"


def summary(reports: list[FileReport], repo: float) -> dict[str, Any]:
    """Repository score, worst file and counts over ``reports`` (all files, not just the shown ones)."""
    worst = min(reports, key=lambda report: report.score, default=None)
    return {
        "repo_score": repo,
        "band": _band(repo),
        "files": len(reports),
        "loc": sum(report.loc for report in reports),
        "smells": sum(len(report.smells) for report in reports),
        "worst_file": {"path": worst.path, "score": worst.score} if worst else None,
    }


def as_json(reports: list[FileReport], totals: dict[str, Any], gate: GateResult, version: int) -> str:
    """Everything, machine-readable; files sorted worst first."""
    data = {
        "config_version": version,
        **totals,
        "gate": {"passed": gate.passed, "violations": gate.violations},
        "reports": [report.to_json() for report in sorted(reports, key=_worst_first)],
    }
    return json.dumps(data, indent=2)


def _worst_first(report: FileReport) -> tuple[float, str]:
    return report.score, report.path


def as_table(
    reports: list[FileReport], totals: dict[str, Any], gate: GateResult, show_all: bool = False
) -> str:
    """Files with smells (or all of them), worst first, each smell with its line."""
    shown = [report for report in sorted(reports, key=_worst_first) if show_all or report.smells]
    width = max((len(report.path) for report in shown), default=4)
    lines = [f"{'Score':>5}  {'LOC':>5}  File", f"{'-' * 5}  {'-' * 5}  {'-' * width}"]
    for report in shown:
        lines.append(f"{report.score:5.2f}  {report.loc:5d}  {report.path}")
        lines += [_smell_line(smell) for smell in report.smells]
    lines += ["", *_summary_lines(totals), *_gate_lines(gate)]
    return "\n".join(lines)


def _smell_line(smell: Smell) -> str:
    return f"{'':14}L{smell.line:<5} {smell.kind:<27} {smell.symbol}: {smell.message}  (-{smell.deduction:g})"


def _summary_lines(totals: dict[str, Any]) -> list[str]:
    worst = totals["worst_file"]
    lines = [
        f"Repository score: {totals['repo_score']:.2f} ({totals['band']}), "
        f"{totals['files']} files, {totals['loc']} code lines"
    ]
    if worst:
        lines.append(f"Worst file:       {worst['score']:.2f} {worst['path']}")
    return lines


def _gate_lines(gate: GateResult) -> list[str]:
    if gate.passed:
        return ["Gate:             passed"]
    return ["Gate:             FAILED", *(f"  - {violation}" for violation in gate.violations)]
