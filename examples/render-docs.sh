#!/usr/bin/env bash
# Renders the recordings shown on the docs' Examples pages into docs/assets/examples.
# Usage: examples/render-docs.sh [narratty build options, e.g. --runtime native]
set -euo pipefail
cd "$(dirname "$0")/.."
out=docs/assets/examples
mkdir -p "$out"

build() { narratty build "$@" --no-end-card; }

for spec in examples/voices/*.narratty.yaml; do
  name=$(basename "$spec" .narratty.yaml)
  build "$spec" -o "$out/voice-$name.mp4" "${@}"
done

build examples/lexicon/lexicon.narratty.yaml -o "$out/lexicon.mp4" "$@"
# The same narration without the spec's lexicon, for comparison.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
sed '/^tts:/,/^terminal:/{/^terminal:/!d}' examples/lexicon/lexicon.narratty.yaml >"$tmp/lexicon.narratty.yaml"
build "$tmp/lexicon.narratty.yaml" -o "$out/lexicon-without.mp4" "$@"

build examples/subtitles/subtitles.narratty.yaml -o "$out/subtitles.mp4" "$@"
build examples/subtitles/subtitles.narratty.yaml --draft -o "$out/draft.mp4" "$@"
build examples/terminal-look/terminal-look.narratty.yaml -o "$out/terminal-look.mp4" "$@"
build examples/cast/cast.narratty.yaml --format cast -o "$out/cast/cast.html" "$@"
narratty build examples/end-card/end-card.narratty.yaml -o "$out/end-card.mp4" "$@"
narratty build examples/editor-layout/editor.narratty.yaml -o "$out/editor-layout.mp4" "$@"
