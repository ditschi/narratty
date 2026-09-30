"""The exported JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from ruamel.yaml import YAML

from narratty.spec.schema import SCHEMA_ID, schema_url, spec_schema, spec_schema_json
from narratty.spec.template import render_template


def test_schema_is_json_with_id() -> None:
    schema = json.loads(spec_schema_json())
    assert schema["$id"] == SCHEMA_ID
    assert schema["title"] == "narratty spec"
    assert "scenes" in schema["required"]
    assert schema["additionalProperties"] is False


def test_committed_schema_is_current() -> None:
    committed = Path(__file__).parents[3] / "schema" / "v1.json"
    assert committed.read_text(encoding="utf-8") == spec_schema_json(), (
        "schema/v1.json is stale; regenerate it with `narratty schema > schema/v1.json`"
    )


@pytest.mark.parametrize(
    ("version", "ref"),
    [("1.2.3", "v1.2.3"), ("0.1.0", "v0.1.0"), ("0.1.1.dev3+g1234abc", "main"), ("0.2.0rc1", "main")],
)
def test_schema_url_follows_the_installed_version(version: str, ref: str) -> None:
    assert schema_url(version) == f"https://raw.githubusercontent.com/ditschi/narratty/{ref}/schema/v1.json"


def test_template_header_points_at_the_versions_schema() -> None:
    first = render_template("1.2.3").splitlines()[0]
    assert first == f"# yaml-language-server: $schema={schema_url('1.2.3')}"


SHORTHANDS = """\
end_card: false
scenes:
  - id: a
    narration: Hi.
    actions:
      - run: ls
      - type_command: pwd
      - enter
      - wait: "done"
      - wait: {screen: done, timeout_ms: 1000}
      - hold: auto
"""
EXAMPLES = sorted((Path(__file__).parents[3] / "examples").glob("**/*.narratty.yaml"))


@pytest.mark.parametrize(
    "text",
    [SHORTHANDS, render_template("1.2.3"), *(path.read_text(encoding="utf-8") for path in EXAMPLES)],
    ids=["shorthands", "template", *(path.parent.name for path in EXAMPLES)],
)
def test_editors_accept_valid_specs(text: str) -> None:
    """What the models accept, the schema accepts too (editors must not flag it)."""
    jsonschema.validate(YAML(typ="safe").load(text), spec_schema())


def test_editors_reject_unknown_actions() -> None:
    data = YAML(typ="safe").load("scenes:\n  - id: a\n    actions: [enterr, {type_comand: ls}]\n")
    errors = list(jsonschema.Draft202012Validator(spec_schema()).iter_errors(data))
    assert len(errors) == 2
