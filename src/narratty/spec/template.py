"""Starter spec written by ``narratty init``."""

from __future__ import annotations

from narratty.spec.schema import schema_url

_TEMPLATE = """\
# yaml-language-server: $schema={schema_url}
version: 1
meta:
  title: "My first narratty video"

tts:
  provider: piper                 # piper | kokoro
  voice: en_US-lessac-medium      # `narratty voices` lists the options

terminal:
  width: 1200
  height: 700
  theme: "Dracula"
  font_size: 22
  typing_speed_ms: 40

workspace:
  source: .                       # directory the demo runs in
  mode: snapshot                  # snapshot (throwaway copy) | rw | ro

scenes:
  - id: intro
    narration: >
      This is a quick look at the files in this project.
    actions:
      - type_command: "ls -la"
      - enter

  - id: wrap
    narration: >
      That is all for now.
    actions:
      - hold: auto
"""


def render_template(version: str) -> str:
    """The starter spec, with the schema line pointing at ``version``'s schema."""
    return _TEMPLATE.replace("{schema_url}", schema_url(version))
