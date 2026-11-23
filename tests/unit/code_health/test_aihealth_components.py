"""The component comparison in tools/aihealth_components.py (scores only, no aihealth run)."""

from __future__ import annotations

import pytest

from tools.aihealth_components import Comparison


@pytest.mark.parametrize(
    ("before", "after", "dropped"),
    [(9.0, 8.99, True), (9.0, 9.0, False), (8.0, 9.0, False), (None, 7.0, False), (7.0, None, False)],
)
def test_any_drop_counts(before: float | None, after: float | None, dropped: bool) -> None:
    assert Comparison("src", before, after).dropped is dropped


def test_line_marks_drops_and_missing_components() -> None:
    assert Comparison("tools", None, 10.0).line() == "tools               - ->  10.00"
    assert Comparison("src", 9.5, 9.0).line().endswith("DROPPED")
