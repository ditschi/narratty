"""Turn smells into file scores and the LOC-weighted repository score."""
# aihealth: disable=primitive_obsession -- temporary cross-check for aihealth, removed afterwards

from __future__ import annotations

from collections import defaultdict
from fnmatch import fnmatch

from .assertions import assertion_smells
from .classes import class_smells
from .config import Config
from .duplication import duplication_smells
from .functions import function_smells
from .metrics import Options, iter_functions, measure
from .model import FileReport, Smell
from .modules import MODULE_SMELLS, module_smells
from .source import Source


def is_test(path: str, config: Config) -> bool:
    """Whether ``path`` gets the test smells."""
    return any(fnmatch(path, pattern) for pattern in config.test_globs)


def file_smells(source: Source, config: Config) -> list[Smell]:
    """Every smell of one file except duplication, which needs all files."""
    options = Options(
        bump_depth=int(config.rule("bumpy_road")["depth"]),
        declared_defaults=tuple(config.rule("many_arguments")["declared_defaults"]),
    )
    functions = [
        measure(name, node, source.code_lines, options) for name, node in iter_functions(source.tree)
    ]
    smells = [smell for metrics in functions for smell in function_smells(metrics, config)]
    smells += class_smells(source, config)
    smells += module_smells(source, functions, config)
    if is_test(source.path, config):
        smells += assertion_smells(source, config)
    return smells


def analyse(sources: list[Source], config: Config) -> list[FileReport]:
    """Score every file in ``sources``."""
    skip_tests = bool(config.rule("duplication")["skip_tests"])
    compared = [source for source in sources if not (skip_tests and is_test(source.path, config))]
    duplicates = duplication_smells(compared, config)
    reports = []
    for source in sources:
        smells = file_smells(source, config) + duplicates.get(source.path, [])
        reports.append(score_file(source, smells, config))
    return reports


def score_file(source: Source, smells: list[Smell], config: Config) -> FileReport:
    """Apply suppressions, then deduct each smell category (capped) from 10."""
    report = FileReport(path=source.path, loc=source.loc)
    smells = smells + _unexplained_suppressions(source, config)
    for smell in sorted(smells, key=lambda smell: (smell.line, smell.kind)):
        target = report.suppressed if is_suppressed(source, smell) else report.smells
        target.append(smell)
    per_kind: dict[str, float] = defaultdict(float)
    for smell in report.smells:
        per_kind[smell.kind] += smell.deduction
    penalty = sum(min(total, config.category_cap) for total in per_kind.values())
    report.score = round(max(config.min_score, 10.0 - penalty), 2)
    return report


def _unexplained_suppressions(source: Source, config: Config) -> list[Smell]:
    rule = config.rule("unexplained_suppression")
    message = "suppression without a reason is ignored: add why after the brackets"
    return [
        Smell("unexplained_suppression", suppression.line, "<comment>", 1, message, rule.weight)
        for suppression in source.suppressions
        if not suppression.reason
    ]


def is_suppressed(source: Source, smell: Smell) -> bool:
    """A reasoned ``# code-health: ignore[kind]`` on the smell's line or right above it.

    Module smells may be suppressed anywhere in the file's leading comment block.
    """
    lines = source.text.splitlines()
    for suppression in source.suppressions:
        if smell.kind not in suppression.kinds or not suppression.reason:
            continue
        if smell.kind in MODULE_SMELLS and _in_header(lines, suppression.line):
            return True
        if _covers(lines, suppression.line, smell.line):
            return True
    return False


def _in_header(lines: list[str], line: int) -> bool:
    return all(text.strip().startswith("#") or not text.strip() for text in lines[: line - 1])


def _covers(lines: list[str], comment_line: int, smell_line: int) -> bool:
    """Same line, or only comments and decorators between the comment and the smell."""
    if comment_line == smell_line:
        return True
    if comment_line > smell_line or not lines[comment_line - 1].strip().startswith("#"):
        return False
    between = lines[comment_line : smell_line - 1]
    return all(text.strip().startswith(("#", "@")) for text in between)


def repo_score(reports: list[FileReport]) -> float:
    """Mean of the file scores weighted by code lines."""
    total = sum(report.loc for report in reports)
    if not total:
        return 10.0
    return round(sum(report.score * report.loc for report in reports) / total, 2)
