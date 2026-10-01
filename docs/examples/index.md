# Examples

Short recordings of narratty's features, each with the spec that made it. The specs
are in [`examples/`](https://github.com/ditschi/narratty/tree/main/examples); build
one with `narratty build <spec>`.

| Example | Shows | Select with |
|---|---|---|
| [Voices and engines](voices.md) | Kokoro and Piper voices, English and German | `tts.provider`, `tts.voice` |
| [Pronunciation](pronunciation.md) | Terms spelled as in the code, spoken correctly | `tts.lexicon` |
| [Terminal look](terminal.md) | Theme, font, prompt, typing speed | `terminal` |
| [Editor layout](editor-layout.md) | Explorer, preview and shell in one tmux window | `terminal.layout: editor` |
| [Subtitles and drafts](subtitles.md) | Burned-in subtitles; a fast preview without TTS | `subtitles`, `--draft` |
| [Asciicast player](cast.md) | Selectable terminal text with a narration track | `--format cast` |
| [Web pages](browser.md) | The project's GitHub page, captured and scrolled | `browser` |
| [Overlays](../user-guide/spec.md#overlays) | Chapter titles, file names, notes over the video | `overlay`, `overlay_styles` |
| [Dev container](../user-guide/environments.md#example-record-a-build-in-the-dev-container) | A build recorded in the project's dev container | `environment.compose` |
| [End card](end-card.md) | "Created with narratty" card with logo, link and QR code | `end_card`, `--no-end-card` |

All recordings except the end card example are built with `--no-end-card`.
`examples/render-docs.sh` rebuilds them.
