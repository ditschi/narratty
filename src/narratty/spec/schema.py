"""JSON Schema for ``.narratty.yaml`` (for editor autocompletion and validation)."""

from __future__ import annotations

import json
from typing import Any

from narratty.spec.model import Spec

# Served from the committed copy on main; a unit test keeps it in sync with the models.
SCHEMA_ID = "https://raw.githubusercontent.com/ditschi/narratty/main/schema/v1.json"


def spec_schema() -> dict[str, Any]:
    """The spec's JSON Schema with ``$schema`` and ``$id`` set."""
    schema = Spec.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
        "title": "narratty spec",
    }


def spec_schema_json() -> str:
    """The schema as pretty-printed JSON."""
    return json.dumps(spec_schema(), indent=2, sort_keys=False) + "\n"
