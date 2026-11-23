"""Smells, suppressions and scores of tools/code_health."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.code_health import config as config_module
from tools.code_health.classes import lcom4
from tools.code_health.config import Config
from tools.code_health.model import FileReport
from tools.code_health.scoring import analyse, repo_score
from tools.code_health.source import Source

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def config() -> Config:
    return config_module.load(ROOT)


def report_of(config: Config, code: str, path: str = "src/sample.py") -> FileReport:
    return analyse([Source.parse(path, textwrap.dedent(code))], config)[0]


def kinds(report: FileReport) -> list[str]:
    return [smell.kind for smell in report.smells]


def branchy(name: str = "f", branches: int = 12) -> str:
    lines = [f"def {name}(x):"] + [f"    if x == {i}:\n        return {i}" for i in range(branches)]
    return "\n".join([*lines, "    return -1", ""])


def test_clean_file_scores_ten(config: Config) -> None:
    report = report_of(config, "def f(x):\n    return x + 1\n")
    assert (report.score, report.smells) == (10.0, [])


def test_complex_method_deducts_by_severity(config: Config) -> None:
    report = report_of(config, branchy(branches=12))
    smell = next(smell for smell in report.smells if smell.kind == "complex_method")
    # CC 13: 0.5 at the threshold of 10, plus 0.1 for each point above.
    assert (smell.value, smell.deduction) == (13, 0.8)


def test_deep_nesting_and_complex_conditionals(config: Config) -> None:
    report = report_of(
        config,
        """
        def f(a, b, c, d, e):
            for x in a:
                if x:
                    while b:
                        if c and d or e and a or b:
                            pass
        """,
    )
    assert {"nested_complexity", "complex_conditional", "many_arguments"} <= set(kinds(report))


def test_category_cap_limits_one_kind_of_smell(config: Config) -> None:
    code = "\n".join(branchy(f"f{i}", branches=11) for i in range(8))
    report = report_of(config, code)
    complex_total = sum(smell.deduction for smell in report.smells if smell.kind == "complex_method")
    assert complex_total > config.category_cap
    assert report.score >= 10.0 - config.category_cap * len(set(kinds(report)))


def test_reasoned_suppression_moves_the_smell_aside(config: Config) -> None:
    code = "# code-health: ignore[complex-method] a lookup table reads best flat\n" + branchy()
    report = report_of(config, code)
    assert "complex_method" not in kinds(report)
    assert [smell.kind for smell in report.suppressed] == ["complex_method"]


def test_suppression_without_reason_is_ignored_and_costs(config: Config) -> None:
    report = report_of(config, "# code-health: ignore[complex_method]\n" + branchy())
    assert {"complex_method", "unexplained_suppression"} <= set(kinds(report))


def test_duplicated_blocks_are_found_across_files(config: Config) -> None:
    block = "".join(f"    value_{i} = compute({i}, value)\n" for i in range(8))
    sources = [
        Source.parse(path, f"def {name}(value):\n{block}") for path, name in [("a.py", "f"), ("b.py", "g")]
    ]
    reports = analyse(sources, config)
    assert [kinds(report) for report in reports] == [["duplication"], ["duplication"]]


def test_large_and_duplicated_assertion_blocks_in_tests(config: Config) -> None:
    asserts = "".join(f"    assert result[{i}] == {i}\n" for i in range(6))
    code = f"def test_one(result):\n{asserts}\ndef test_two(result):\n{asserts}"
    report = report_of(config, code, path="tests/unit/test_sample.py")
    assert sorted(set(kinds(report))) == ["duplicated_assertion_block", "large_assertion_block"]


def test_low_cohesion_counts_unrelated_method_groups() -> None:
    members = {"a": {"x"}, "b": {"x", "y"}, "c": {"z"}, "d": {"c"}}
    assert lcom4(members) == 2


def test_class_with_unrelated_halves_has_low_cohesion(config: Config) -> None:
    methods = "".join(
        f"    def {name}(self):\n        return self.{attr}\n"
        for name, attr in [("a", "x"), ("b", "x"), ("c", "y"), ("d", "y")]
    )
    report = report_of(config, f"class Split:\n{methods}")
    assert kinds(report) == ["low_cohesion"]


def test_repo_score_is_weighted_by_code_lines() -> None:
    reports = [FileReport("a.py", loc=300, score=10.0), FileReport("b.py", loc=100, score=6.0)]
    assert repo_score(reports) == 9.0
