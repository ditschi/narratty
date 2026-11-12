#!/usr/bin/env bash
# Renders the docs videos made from Markdown pages into docs/assets/examples. CI runs it
# before every docs deploy (.github/actions/render-docs-videos), so these videos always
# match their page and are not committed. The other videos: examples/render-docs.sh.
# Usage: examples/render-ci-videos.sh [narratty build options, e.g. --image narratty:docs]
set -euo pipefail
cd "$(dirname "$0")/.."
out=docs/assets/examples
mkdir -p "$out"

# The video of docs/user-guide/markdown.md, made from that page.
narratty build examples/markdown/markdown.narratty.yaml --no-end-card -o "$out/markdown.mp4" "$@"
