"""The exported JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

from narratty.spec.schema import SCHEMA_ID, spec_schema_json


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
