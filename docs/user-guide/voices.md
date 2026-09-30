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

## Audio cache

Every clip is stored under a key made of the provider, voice, normalized text, model
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
