"""``narratty schema``: print the JSON Schema for ``.narratty.yaml``."""

from __future__ import annotations


def schema_command() -> None:
    """Print the spec's JSON Schema (point your editor's YAML plugin at it)."""
    import sys

    from narratty.spec.schema import spec_schema_json

    sys.stdout.write(spec_schema_json())
