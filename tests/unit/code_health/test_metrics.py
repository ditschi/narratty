"""Raw metrics of tools/code_health against hand-counted examples."""

from __future__ import annotations

import ast
import textwrap

import pytest

from tools.code_health.metrics import Cognitive, FunctionMetrics, Options, bumps, is_primitive, measure


def metrics_of(code: str) -> FunctionMetrics:
    tree = ast.parse(textwrap.dedent(code))
    node = tree.body[0]
    assert isinstance(node, ast.FunctionDef)
    lines = set(range(1, len(code.splitlines()) + 1))
    return measure(node.name, node, lines, Options(declared_defaults=("typer.Option",)))


def test_cyclomatic_counts_branches_loops_and_boolean_operators() -> None:
    metrics = metrics_of(
        """
        def f(a, b):
            if a and b:
                return 1
            elif a:
                return 2
            for _ in b:
                pass
            return [x for x in b if x]
        """
    )
    # 1 + if + and + elif + for + comprehension (for, if)
    assert metrics.cyclomatic == 7


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("def f(a):\n    if a:\n        return 1\n", 1),
        ("def f(a):\n    if a:\n        for x in a:\n            pass\n", 3),
        ("def f(a, b):\n    if a:\n        pass\n    elif b:\n        pass\n    else:\n        pass\n", 3),
        ("def f(a, b, c):\n    return a and b or c\n", 2),
        ("def f(a):\n    try:\n        pass\n    except ValueError:\n        if a:\n            pass\n", 3),
    ],
)
def test_cognitive_complexity_follows_sonar(code: str, expected: int) -> None:
    node = ast.parse(code).body[0]
    assert isinstance(node, ast.FunctionDef)
    assert Cognitive.of(node) == expected


def test_nesting_ignores_elif_chains_and_with_blocks() -> None:
    metrics = metrics_of(
        """
        def f(a):
            with open(a) as handle:
                if a:
                    pass
                elif handle:
                    for line in handle:
                        while line:
                            pass
        """
    )
    assert metrics.nesting == 3


def test_bumps_count_separate_nested_blocks() -> None:
    body = ast.parse(
        textwrap.dedent(
            """
            if a:
                if b:
                    pass
            x = 1
            for c in d:
                if c:
                    pass
            if e:
                pass
            """
        )
    ).body
    assert bumps(body, depth=2) == 2


def test_parameters_skip_self_and_declared_cli_options() -> None:
    metrics = metrics_of(
        """
        def f(self, a: str, b: int | None, *, c: list[str], d: bool = typer.Option(False)):
            pass
        """
    )
    assert (metrics.params, metrics.annotated_params, metrics.primitive_params) == (3, 3, 2)


@pytest.mark.parametrize(
    ("annotation", "primitive"),
    [
        ("str", True),
        ("int | None", True),
        ("Optional[float]", True),
        ("Annotated[bool, typer.Option()]", True),
        ("Path", False),
        ("list[str]", False),
        ("str | Path", False),
    ],
)
def test_primitive_annotations(annotation: str, primitive: bool) -> None:
    assert is_primitive(ast.parse(annotation, mode="eval").body) is primitive


def test_tests_and_fixtures_are_marked_as_injected() -> None:
    assert metrics_of("@pytest.fixture\ndef thing(a, b):\n    pass\n").injected
    assert metrics_of("def test_it(a):\n    pass\n").injected
    assert not metrics_of("def helper(a):\n    pass\n").injected


def test_conditions_report_line_and_operator_count() -> None:
    metrics = metrics_of("def f(a, b, c):\n    while a and b or c:\n        pass\n")
    assert metrics.conditions == [(2, 2)]
