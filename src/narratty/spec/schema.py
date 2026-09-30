"""JSON Schema for ``.narratty.yaml`` (for editor autocompletion and validation)."""

from __future__ import annotations

import json
import re
from typing import Any

from narratty.spec.model import Spec

# The schema is committed as schema/v1.json (a unit test keeps it in sync with the models),
# so every release tag serves the schema of that release.
SCHEMA_BASE = "https://raw.githubusercontent.com/ditschi/narratty"
SCHEMA_PATH = "schema/v1.json"
SCHEMA_ID = f"{SCHEMA_BASE}/main/{SCHEMA_PATH}"
_RELEASE = re.compile(r"^\d+\.\d+\.\d+$")


def schema_url(version: str) -> str:
    """URL of the schema matching an installed narratty ``version``.

    Releases (``1.2.3``) point at their git tag; development builds point at ``main``.
    """
    ref = f"v{version}" if _RELEASE.match(version) else "main"
    return f"{SCHEMA_BASE}/{ref}/{SCHEMA_PATH}"


def _add_shorthands(schema: dict[str, Any]) -> dict[str, Any]:
    """Allow the short forms the models accept in ``mode="before"`` validators.

    Pydantic only describes the long forms, so without this editors flag valid specs
    (``- enter``, ``wait: "done"``, ``end_card: false``).
    """
    defs = schema["$defs"]
    actions = defs["Scene"]["properties"]["actions"]["items"]["oneOf"]
    actions.append({"const": "enter", "description": defs["Enter"]["description"]})
    wait = defs["Wait"]["properties"]["wait"]
    defs["Wait"]["properties"]["wait"] = {
        "anyOf": [{"type": "string", "description": "Regular expression; short for {screen: ...}."}, wait]
    }
    end_card = schema["properties"]["end_card"]
    schema["properties"]["end_card"] = {
        "anyOf": [
            {"type": "boolean", "description": "Short for {enabled: ...}."},
            {"$ref": end_card.pop("$ref")},
        ],
        **end_card,
    }
    return schema


def spec_schema() -> dict[str, Any]:
    """The spec's JSON Schema with ``$schema`` and ``$id`` set."""
    schema = _add_shorthands(Spec.model_json_schema())
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
        "title": "narratty spec",
    }


def spec_schema_json() -> str:
    """The schema as pretty-printed JSON."""
    return json.dumps(spec_schema(), indent=2, sort_keys=False) + "\n"
