# Examples

Short recordings of narratty's features, each with the spec that made it. The specs
are in [`examples/`](https://github.com/ditschi/narratty/tree/main/examples); build
one with `narratty build <spec>`.

| Example | Shows | Select with |
|---|---|---|
| [Voices and engines](voices.md) | Kokoro and Piper voices, English and German | `tts.provider`, `tts.voice` |
| [Pronunciation](pronunciation.md) | Terms spelled as in the code, spoken correctly | `tts.lexicon` |
| [Terminal look](terminal.md) | Theme, font, prompt, typing speed | `terminal` |
| [Editor layout](editor-layout.md) | Explorer, preview and shell in one tmux window | demo toolkit, hidden scenes |
| [Subtitles and drafts](subtitles.md) | Burned-in subtitles; a fast preview without TTS | `subtitles`, `--draft` |
| [Asciicast player](cast.md) | Selectable terminal text with a narration track | `--format cast` |
| [End card](end-card.md) | "Created with narratty" card with link and QR code | `end_card`, `--no-end-card` |

All recordings except the end card example are built with `--no-end-card`.
`examples/render-docs.sh` rebuilds them.
