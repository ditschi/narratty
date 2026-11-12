"""The videos in the docs must match the specs they are rendered from.

``examples/render-docs.sh`` renders them and stores ``narratty compile --fingerprint`` of
each spec as ``<name>.fingerprint`` next to it: what its videos show and say, Markdown
sources included. A spec or doc changed since means its videos are outdated.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from narratty.spec.compile import fingerprint

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "examples" / "render-docs.sh"


def _rendered_specs() -> list[Path]:
    text = SCRIPT.read_text(encoding="utf-8")
    named = {ROOT / match for match in re.findall(r"examples/[\w./-]+\.narratty\.yaml", text)}
    looped = {
        path for pattern in re.findall(r"for spec in (examples/[^;\s]+)", text) for path in ROOT.glob(pattern)
    }
    return sorted(named | looped)


SPECS = _rendered_specs()


def test_the_script_names_its_specs() -> None:
    assert ROOT / "examples" / "markdown" / "markdown.narratty.yaml" in SPECS
    assert len([spec for spec in SPECS if spec.parent.name == "voices"]) > 1


@pytest.mark.parametrize("spec", SPECS, ids=lambda path: path.name.removesuffix(".narratty.yaml"))
def test_docs_videos_match_their_spec(spec: Path) -> None:
    stored = spec.with_name(spec.name.removesuffix(".narratty.yaml") + ".fingerprint")
    rerender = f"`examples/render-docs.sh --only {spec.relative_to(ROOT)}`"
    assert stored.is_file(), f"{stored.relative_to(ROOT)} is missing; render the videos with {rerender}"
    assert fingerprint(spec) == stored.read_text(encoding="utf-8").strip(), (
        f"{spec.relative_to(ROOT)} or the Markdown it reads changed since its videos were rendered; "
        f"re-render them with {rerender} and commit the videos and the fingerprint"
    )
