# Voices and audio cache

narratty speaks with local text-to-speech engines; nothing is sent to a cloud service.

| Provider | Sound | Languages | Download |
|---|---|---|---|
| `kokoro` (default) | natural | English (US, UK), Spanish, French, Italian, Portuguese, Hindi, Japanese, Chinese | one 205 MB model shared by all voices (`af_heart`, `bf_emma`, …) |
| `piper` | clear, more synthetic | many, including German | about 60 MB per voice (`en_US-lessac-medium`, `de_DE-thorsten-medium`, …) |

Both come with narratty. Without a `tts` block a spec uses Kokoro with `af_heart`;
with only `provider`, the voice defaults to that provider's first voice:

```yaml
tts:
  provider: piper
  voice: de_DE-thorsten-medium
  piper:
    length_scale: 1.1
```

narratty uses Kokoro's fp16 model: half the size of the full model, faster on a CPU
and sounds the same.

## Listing and downloading voices

```bash
narratty voices                      # curated voices of both providers
narratty voices --provider piper --installed
narratty voices pull bf_emma
```

`narratty tts` and `narratty build` download a missing voice on first use; pass
`--offline` (or set `NARRATTY_OFFLINE=1`) to fail instead. Kokoro model files are
checked against pinned SHA-256 sums.

Voices live in the data directory, `~/.local/share/narratty` on Linux (override with
`NARRATTY_DATA_DIR`). To use a Piper voice that is not in the curated list, copy its
`<id>.onnx` and `<id>.onnx.json` into `<data dir>/piper/` and set `tts.voice: <id>`.

## Synthesizing narration

```bash
narratty tts demo.narratty.yaml
```

prints one row per narrated scene with the clip's length and whether it came from the
cache.

## Pronunciation

Write narration with the real spelling of technical terms (`.bazelrc`, `kubectl`,
`bm_rat_b`), not a phonetic workaround such as "dot Basel R C". The text stays
searchable and correct in the spec. The engines already say most terms well
(`bazel`, `YAML`, `bm_rat_b`), and narratty speaks a leading dot as "dot". For the
rest, the lexicon tells the engine how to say a term:

```yaml
tts:
  lexicon:
    k8s: "kubernetes"
    kubectl: "cube C T L"
```

Entries come from four levels; a later level overrides an earlier one:

| Level | Where |
|---|---|
| Built-in | shipped with narratty (`kubectl`, `stdout`, `CLI`, …); English voices only |
| User | `~/.config/narratty/lexicon.toml` |
| Project | nearest `narratty.lexicon.toml` from the spec's directory up to the git root |
| Spec | `tts.lexicon` |

The TOML files use the same pairs:

```toml
kubectl = "cube C T L"
[k8s]
say = "kubernetes"
```

- Matching is whole-word. A term with a capital letter matches only that case
  (`API`); an all-lowercase term matches any case (`k8s`, `K8s`).
- A leading dot is spoken as "dot", also before a term with an entry:
  `.kubectl` becomes "dot cube C T L".
- Only the spoken text changes; the lexicon result is part of the audio cache key.
- Sandboxed runs get the user and project entries from the host.

```bash
narratty lexicon show demo.narratty.yaml    # merged entries and their source
narratty lexicon check demo.narratty.yaml   # dotted, snake_case, camelCase, ALL-CAPS or digit words without an entry
```

When an AI writes the scene list, tell it to spell terms as written in the code and to
put pronunciations in `tts.lexicon`; then run `narratty lexicon check` and listen to
`narratty tts`.

## Audio cache

Every clip is stored under a key made of the provider, voice, spoken text, model
version and provider options, so only changed narration is synthesized again. The
cache is in `~/.cache/narratty` on Linux (override with `NARRATTY_CACHE_DIR`).

```bash
narratty cache info
narratty cache prune --older-than 30d     # clips not used for 30 days
narratty cache prune --all
```

## Licences

Piper (`piper-tts`) is GPL-3.0; narratty only runs it as a separate process, so
narratty itself stays MIT. Each Piper voice has its own licence, linked from its model
card (see `narratty voices` and the
[piper-voices repository](https://huggingface.co/rhasspy/piper-voices)). The Kokoro
model is Apache-2.0.
