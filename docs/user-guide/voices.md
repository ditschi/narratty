# Voices and audio cache

narratty speaks with local text-to-speech engines; nothing is sent to a cloud service.

| Provider | Install | Voices |
|---|---|---|
| `piper` (default) | comes with narratty | `en_US-lessac-medium` and the other curated Piper voices |
| `kokoro` | `uv tool install 'narratty[kokoro]'` | `af_heart`, `bf_emma`, … (one ~300 MB model shared by all voices) |

Pick one in the spec:

```yaml
tts:
  provider: kokoro
  voice: af_heart
  kokoro:
    speed: 1.1
```

## Listing and downloading voices

```bash
narratty voices                      # curated voices of both providers
narratty voices --provider piper --installed
narratty voices pull en_GB-alan-medium
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
