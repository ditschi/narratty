# Subtitles and drafts

## Subtitles

Subtitles come from the narration, one cue per sentence. This spec burns them in:

<video controls width="100%" src="../../assets/examples/subtitles.mp4"></video>

```yaml
--8<-- "examples/subtitles/subtitles.narratty.yaml:2:"
```

| `subtitles` / `--subtitles` | Result |
|---|---|
| `files` | `.srt` and `.vtt` beside the video |
| `track` | Soft track in the mp4, switchable in the player |
| `burn` | Drawn into the picture |

## Draft

`--draft` previews actions and timing without TTS: estimated narration lengths, half
size, 10 fps, narration burned in as subtitles. The same spec as a draft:

<video controls width="100%" src="../../assets/examples/draft.mp4"></video>

```bash
narratty build examples/subtitles/subtitles.narratty.yaml --draft   # subtitles.draft.mp4
```

See [Building a video](../user-guide/building.md#subtitles) for details.
