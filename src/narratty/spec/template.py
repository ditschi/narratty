"""Starter spec written by ``narratty init``."""

from __future__ import annotations

import json
import re

from narratty.spec.schema import schema_url

_TEMPLATE = """\
# yaml-language-server: $schema={schema_url}
# Write only what differs from the defaults; `narratty schema` lists every key.
version: 1
meta:
  title: "My first narratty video"

# tts:
#   voice: af_heart               # `narratty voices` lists the options
#   lexicon:                      # say terms differently from how the narration spells them
#     k8s: kubernetes
# terminal:
#   width: 1200
#   height: 700
#   theme: Dracula
# workspace:
#   source: .                     # directory the demo runs in (a throwaway copy by default)

scenes:
  - id: intro
    narration: >
      This is a quick look at the files in this project.
    actions:
      - run: ls -la               # types the command, presses Enter, pauses briefly

  - id: wrap                      # no actions: the scene lasts as long as its narration
    narration: That is all for now.
"""


def render_template(version: str) -> str:
    """The starter spec, with the schema line pointing at ``version``'s schema."""
    return _TEMPLATE.replace("{schema_url}", schema_url(version))


_MARKDOWN_TEMPLATE = """\
# yaml-language-server: $schema={schema_url}
# The video of {doc}: its paragraphs are spoken, its code blocks run.
# Write only what differs from the defaults; `narratty schema` lists every key.

# tts:
#   voice: af_heart               # `narratty voices` lists the options
# workspace:
#   source: .                     # directory the commands run in (a throwaway copy by default)

scenes:
  # - id: intro                   # scenes written here can stand before and after the doc
  #   narration: A short tour of the project.
  - markdown: {doc}
    # sections: [install, usage]  # only these sections, by heading; unset: the whole doc
    # heading_overlays: 2         # show the headings down to level 2 over the video
"""


def render_markdown_template(version: str, doc: str) -> str:
    """A starter spec for the Markdown doc at ``doc`` (relative to the spec)."""
    value = doc if re.fullmatch(r"[\w./-]+", doc) else json.dumps(doc)
    text = _MARKDOWN_TEMPLATE.replace("{schema_url}", schema_url(version))
    return text.replace("markdown: {doc}", f"markdown: {value}").replace("{doc}", doc)
