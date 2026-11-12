"""JSON Schema for ``.narratty.yaml`` (for editor autocompletion and validation)."""

from __future__ import annotations

import json
import re
from typing import Any

from narratty.spec.model import MarkdownEntry, Spec

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


# Still accepted; editors that understand deprecationMessage (yaml-language-server) nudge to `key: Enter`.
_LEGACY_ENTER = {"deprecated": True, "deprecationMessage": "Write `key: Enter` instead."}


def _add_shorthands(schema: dict[str, Any]) -> dict[str, Any]:
    """Allow the short forms the models accept in ``mode="before"`` validators.

    Pydantic only describes the long forms, so without this editors flag valid specs
    (``- enter``, ``- diff``, ``wait: "done"``, ``end_card: false``).
    """
    defs = schema["$defs"]
    override = defs["BlockOverride"]["properties"]
    for action_list in (defs["Scene"]["properties"]["actions"], override["before"], override["after"]):
        actions = action_list["items"]["oneOf"]
        actions.append({"const": "enter", "description": defs["Enter"]["description"], **_LEGACY_ENTER})
        actions.append({"const": "diff", "description": "Show the whole diff; short for {diff: true}."})
    defs["Enter"].update(_LEGACY_ENTER)
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


def _add_markdown_entries(schema: dict[str, Any]) -> dict[str, Any]:
    """Allow ``markdown`` entries in ``scenes``; the loader expands them before validation."""
    entry = MarkdownEntry.model_json_schema()
    schema["$defs"] |= entry.pop("$defs")
    schema["$defs"]["MarkdownEntry"] = entry
    # if/then/else instead of anyOf, so editors report a scene's own errors, not "no match".
    schema["properties"]["scenes"]["items"] = {
        "if": {"type": "object", "required": ["markdown"]},
        "then": {"$ref": "#/$defs/MarkdownEntry"},
        "else": {"$ref": "#/$defs/Scene"},
    }
    return schema


def spec_schema() -> dict[str, Any]:
    """The spec's JSON Schema with ``$schema`` and ``$id`` set."""
    schema = _add_shorthands(_add_markdown_entries(Spec.model_json_schema()))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
        "title": "narratty spec",
    }


def spec_schema_json() -> str:
    """The schema as pretty-printed JSON."""
    return json.dumps(spec_schema(), indent=2, sort_keys=False) + "\n"
