#!/usr/bin/env bash
# Renders the recordings shown on the docs into docs/assets/examples; CI renders the ones
# made from Markdown (examples/render-ci-videos.sh), which are not committed.
# Usage: examples/render-docs.sh [--only PATTERN] [narratty build options, e.g. --runtime native]
#   --only PATTERN  renders only the specs whose path contains PATTERN (e.g. browser)
# Each spec gets <name>.fingerprint next to it (`narratty compile --fingerprint`): what its
# videos show and say, Markdown sources included. A unit test fails when a spec or its
# Markdown changed since its videos were rendered; re-render with --only and commit both.
set -euo pipefail
cd "$(dirname "$0")/.."
out=docs/assets/examples
mkdir -p "$out"

only=""
if [[ "${1:-}" == "--only" ]]; then
  only=$2
  shift 2
fi

selected() { [[ -z "$only" || "$1" == *"$only"* ]]; }
fingerprint() { narratty compile --fingerprint "$1" >"${1%.narratty.yaml}.fingerprint"; }

# build SPEC [options]: without the end card; records the fingerprint of specs in examples/.
build() {
  selected "$1" || return 0
  narratty build "$@" --no-end-card
  if [[ "$1" == examples/* ]]; then fingerprint "$1"; fi
}

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
if selected examples/end-card/end-card.narratty.yaml; then
  narratty build examples/end-card/end-card.narratty.yaml -o "$out/end-card.mp4" "$@"
  fingerprint examples/end-card/end-card.narratty.yaml
fi
build examples/editor-layout/editor.narratty.yaml -o "$out/editor-layout.mp4" "$@"
build examples/browser/browser.narratty.yaml -o "$out/browser.mp4" --yes "$@"   # needs network
