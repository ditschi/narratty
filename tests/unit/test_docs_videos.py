"""The videos in the docs must match the specs they are rendered from.

``examples/render-docs.sh`` renders the committed ones and stores ``narratty compile
--fingerprint`` of each spec as ``<name>.fingerprint`` next to it; a spec changed since
means its videos are outdated. Videos made from Markdown are rendered in CI before each
docs deploy instead (``examples/render-ci-videos.sh``), so they are never outdated.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from narratty.spec.compile import fingerprint

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "examples" / "render-docs.sh"
CI_SCRIPT = ROOT / "examples" / "render-ci-videos.sh"


def _rendered_specs(script: Path) -> list[Path]:
    text = script.read_text(encoding="utf-8")
    named = {ROOT / match for match in re.findall(r"examples/[\w./-]+\.narratty\.yaml", text)}
    looped = {
        path for pattern in re.findall(r"for spec in (examples/[^;\s]+)", text) for path in ROOT.glob(pattern)
    }
    return sorted(named | looped)


SPECS = _rendered_specs(SCRIPT)
CI_SPECS = _rendered_specs(CI_SCRIPT)


def _reads_markdown(spec: Path) -> bool:
    from narratty.spec.compile import has_markdown
    from narratty.spec.loader import parse_document, read_spec_text

    return has_markdown(parse_document(read_spec_text(spec), spec))


def test_the_scripts_name_their_specs() -> None:
    assert len([spec for spec in SPECS if spec.parent.name == "voices"]) > 1
    assert ROOT / "examples" / "markdown" / "markdown.narratty.yaml" in CI_SPECS


def test_videos_made_from_markdown_are_rendered_in_ci() -> None:
    """They follow their page with every docs deploy; committed copies would go stale."""
    assert [spec for spec in SPECS if _reads_markdown(spec)] == []
    assert all(_reads_markdown(spec) for spec in CI_SPECS)


@pytest.mark.parametrize("spec", SPECS, ids=lambda path: path.name.removesuffix(".narratty.yaml"))
def test_docs_videos_match_their_spec(spec: Path) -> None:
    stored = spec.with_name(spec.name.removesuffix(".narratty.yaml") + ".fingerprint")
    rerender = f"`examples/render-docs.sh --only {spec.relative_to(ROOT)}`"
    assert stored.is_file(), f"{stored.relative_to(ROOT)} is missing; render the videos with {rerender}"
    assert fingerprint(spec) == stored.read_text(encoding="utf-8").strip(), (
        f"{spec.relative_to(ROOT)} or the Markdown it reads changed since its videos were rendered; "
        f"re-render them with {rerender} and commit the videos and the fingerprint"
    )
