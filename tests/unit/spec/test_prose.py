"""Key points of paragraphs for prose slides."""

from __future__ import annotations

import pytest

from narratty.spec.markdown.prose import key_point


@pytest.mark.parametrize(
    ("source", "point"),
    [
        ("Short one.", "Short one"),
        ("The doc is read in order. Paragraphs collect until a block runs.", "The doc is read in order"),
        (
            "Text after a slide (an image, diagram or table) or after a block with `say: after` belongs to "
            "it, up to the next block.",
            "Text after a slide or after a block with `say: after` belongs to it",
        ),
        (
            "Every command waits until the prompt is back, so the next one starts after it has finished.",
            "Every command waits until the prompt is back",
        ),
        (
            "A line `...` stands for any lines, also none; `...` within a line for any text, as in `Python 3...`.",
            "A line `...` stands for any lines",
        ),
        ("See [the guide](guide.md) for more.", "See the guide for more"),
        ("Run `make test (all)` first.", "Run `make test (all)` first"),
        ("Version 1.2 is out. It is faster.", "Version 1.2 is out"),
        (
            "Hi, short, sentence, with commas but under the limit.",
            "Hi, short, sentence, with commas but under the limit",
        ),
    ],
)
def test_key_point(source: str, point: str) -> None:
    assert key_point(source) == point
