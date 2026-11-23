"""Test smells: Large Assertion Blocks and Duplicated Assertion Blocks."""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterator

from .config import Config
from .metrics import iter_functions
from .model import Smell
from .source import Source

Run = list[ast.Assert]


def assertion_smells(source: Source, config: Config) -> list[Smell]:
    """Assertion block findings for the test functions of ``source``."""
    tests = [(name, node) for name, node in iter_functions(source.tree) if node.name.startswith("test")]
    runs = {name: list(_assert_runs(node.body)) for name, node in tests}
    return _large_blocks(runs, config) + _duplicated_blocks(runs, config)


def _assert_runs(body: list[ast.stmt]) -> Iterator[Run]:
    """Maximal sequences of consecutive ``assert`` statements, nested blocks included."""
    run: Run = []
    for stmt in body:
        if isinstance(stmt, ast.Assert):
            run.append(stmt)
            continue
        if run:
            yield run
            run = []
        for block in _blocks(stmt):
            yield from _assert_runs(block)
    if run:
        yield run


def _blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return []
    blocks = [getattr(stmt, name, None) for name in ("body", "orelse", "finalbody")]
    blocks += [handler.body for handler in getattr(stmt, "handlers", [])]
    blocks += [case.body for case in getattr(stmt, "cases", [])]
    return [block for block in blocks if isinstance(block, list)]


def _large_blocks(runs: dict[str, list[Run]], config: Config) -> list[Smell]:
    rule = config.rule("large_assertion_block")
    return [
        Smell(
            "large_assertion_block",
            run[0].lineno,
            name,
            len(run),
            f"{len(run)} consecutive asserts (threshold {rule.threshold:g})",
            rule.deduction(len(run)),
        )
        for name, test_runs in runs.items()
        for run in test_runs
        if len(run) >= rule.threshold
    ]


def _duplicated_blocks(runs: dict[str, list[Run]], config: Config) -> list[Smell]:
    rule = config.rule("duplicated_assertion_block")
    size = int(rule.threshold)
    smells: dict[str, Smell] = {}
    for tests in _owners(runs, size).values():
        for name, line in sorted(tests.items()) if len(tests) > 1 else []:
            others = ", ".join(sorted(set(tests) - {name}))
            message = f"{size} asserts repeated in {others}"
            smells.setdefault(
                name, Smell("duplicated_assertion_block", line, name, size, message, rule.weight)
            )
    return list(smells.values())


def _owners(runs: dict[str, list[Run]], size: int) -> dict[tuple[str, ...], dict[str, int]]:
    """For each block of ``size`` asserts, the tests holding it and the line where it starts."""
    owners: dict[tuple[str, ...], dict[str, int]] = defaultdict(dict)
    for name, test_runs in runs.items():
        for key, line in _windows(test_runs, size):
            owners[key].setdefault(name, line)
    return owners


def _windows(test_runs: list[Run], size: int) -> Iterator[tuple[tuple[str, ...], int]]:
    for run in test_runs:
        dumps = [ast.dump(stmt) for stmt in run]
        for start in range(len(run) - size + 1):
            yield tuple(dumps[start : start + size]), run[start].lineno
