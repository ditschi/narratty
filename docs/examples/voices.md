# Voices and engines

Two local engines: **Kokoro** (default, natural) and **Piper** (more languages,
including German). Pick them in the spec's `tts` block; `narratty voices` lists the
curated voices. See [Voices and audio cache](../user-guide/voices.md).

=== "Kokoro af_heart"

    Default; the spec needs no `tts` block for it.

    <video controls width="100%" src="../../assets/examples/voice-kokoro-af_heart.mp4"></video>

    ```yaml
    --8<-- "examples/voices/kokoro-af_heart.narratty.yaml:2:4"
    ```

=== "Kokoro am_michael"

    <video controls width="100%" src="../../assets/examples/voice-kokoro-am_michael.mp4"></video>

    ```yaml
    --8<-- "examples/voices/kokoro-am_michael.narratty.yaml:2:4"
    ```

=== "Kokoro bf_emma"

    <video controls width="100%" src="../../assets/examples/voice-kokoro-bf_emma.mp4"></video>

    ```yaml
    --8<-- "examples/voices/kokoro-bf_emma.narratty.yaml:2:4"
    ```

=== "Piper lessac"

    <video controls width="100%" src="../../assets/examples/voice-piper-en_US-lessac-medium.mp4"></video>

    ```yaml
    --8<-- "examples/voices/piper-en_US-lessac-medium.narratty.yaml:2:4"
    ```

=== "Piper thorsten (German)"

    <video controls width="100%" src="../../assets/examples/voice-piper-de_DE-thorsten-medium.mp4"></video>

    ```yaml
    --8<-- "examples/voices/piper-de_DE-thorsten-medium.narratty.yaml:2:4"
    ```

- With only `provider`, the voice is that provider's first curated voice.
- Speed: `kokoro.speed` (1.0 = normal) or `piper.length_scale` (larger is slower).
- Voices download on first use; `narratty voices pull <id>` fetches one ahead.

```bash
narratty build examples/voices/kokoro-bf_emma.narratty.yaml
```
