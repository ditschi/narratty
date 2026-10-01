# Building a video

```bash
narratty build demo.narratty.yaml            # writes demo.mp4 next to the spec
narratty build demo.narratty.yaml -o out/tour.mp4 --work-dir out/work
```

`build` runs the whole pipeline:

1. **Narration.** Each narrated scene's text is synthesized, or taken from the
   [audio cache](voices.md#audio-cache).
2. **Timeline.** Each scene lasts as long as its actions, or as long as its
   narration plus `timing.narration_buffer_ms`, whichever is longer.
3. **Tape.** A [VHS](https://github.com/charmbracelet/vhs) tape types your commands
   and pauses to fill each scene.
4. **Recording.** VHS records a silent video, running the shell in
   `workspace.source`.
5. **Mix.** Every clip is placed at the start of its scene in one narration track,
   which is muxed onto the video as AAC.
6. **Check.** The result must contain video and audio, and its length must be
   within `--max-drift` of the plan (10% by default). Otherwise the build exits
   with code 6.

After the last scene and the tail comes the end card (4 s by default; see
[`end_card`](spec.md#end_card)); `--no-end-card` leaves it out.

With `--work-dir` the tape, the silent video and the narration track are kept for
inspection.

## Subtitles

```bash
narratty build demo.narratty.yaml --subtitles files   # demo.mp4, demo.srt, demo.vtt
```

Subtitles come from the narration: each clip becomes one cue per sentence, and long
sentences are split so a cue fits in two lines. Cues show the text as written in the
spec. Set the mode with [`subtitles`](spec.md#top-level) or `--subtitles`:

| Mode | Result |
|---|---|
| `none` | No subtitles (default) |
| `files` | `.srt` and `.vtt` beside the video |
| `track` | A soft subtitle track in the mp4; players can switch it on and off |
| `burn` | Drawn into the picture; re-encodes the video |

With `--format cast`, every mode except `none` writes the `.srt` and `.vtt` beside
the page.

## Draft

```bash
narratty build demo.narratty.yaml --draft      # writes demo.draft.mp4
```

A draft checks actions and timing without waiting for TTS:

- narration lengths are estimated from the text (about 14 characters per second,
  scaled by the voice speed); no voice is loaded or downloaded;
- VHS captures 10 frames per second instead of 30, and the video is encoded at half
  size; the terminal itself keeps its size, so output and `wait` behave as in the
  real build;
- the video is silent and the narration is burned in as subtitles, so you see
  where each line would be spoken (`--subtitles` picks another mode).

`narratty plan SPEC --draft` prints the estimated timeline. `--draft` only applies to
mp4 output.

## Asciicast with narration

```bash
narratty build demo.narratty.yaml --format cast   # demo.cast, demo.mp3, demo.html
```

Instead of a video, this writes an [asciicast](https://docs.asciinema.org/manual/asciicast/v2/)
(`.cast`), the narration as MP3, and an HTML page that plays both with
[asciinema-player](https://docs.asciinema.org/manual/player/). The player uses the
audio as its clock, so pausing and seeking stay in sync. Terminal text stays
selectable, and the cast is a few kilobytes.

- **The page is self-contained**: cast and audio are embedded, so it works opened
  from disk or on any static host. The player itself loads from jsDelivr.
- **`-o`** names the page; the `.cast` and `.mp3` go beside it.
- **Recording**: VHS cannot write asciicasts, so narratty runs the scenes itself in a
  pseudo-terminal of the same size and shell. Each clip is placed at its scene's
  recorded start, so there is no drift check.
- **Size**: columns and rows follow `terminal.width`, `height` and `font_size`. The
  theme applies when asciinema-player has one of the same name (Dracula, Monokai,
  Nord, Solarized, Tango, …).
- **Overlays** are drawn over the player as HTML boxes and follow its clock. The
  `.cast` itself has none: asciicast has no way to store them.
- **`wait`** matches the text printed since the last clear, not a rendered screen;
  full-screen programs such as `vim` are not modelled.

To embed the recording in your own page, use the `.cast` and `.mp3`:

```js
AsciinemaPlayer.create("demo.cast", element, { audioUrl: "demo.mp3" });
```

Seeking needs a server that supports range requests, as most static hosts do.

## Looking before rendering

| Command | Shows |
|---|---|
| `narratty plan SPEC` | Each scene's start, action time, narration length and the total |
| `narratty plan SPEC --draft` | The same with estimated narration lengths, without TTS |
| `narratty tape SPEC` | The generated VHS tape |
| `narratty render SPEC` | Records only the silent video (`demo.silent.mp4`) |

## How sync works

Narration starts when its scene starts, so the voice talks while the command is
typed. Set `narration_start: after_actions` on a scene to speak only after its
actions. The pause that fills a scene goes where the scene has `hold: auto`, or
after its actions otherwise.

VHS's real timing differs from its nominal timing by a few percent, depending on the
machine. narratty measures the recorded video and stretches the clip positions to
match, so each clip still starts with its scene.

## Things to know

- **`wait` matches the whole screen**, including the command you just typed. Wait for
  text that only the command's output contains, e.g. `wait: {screen: "Build
  succeeded"}` rather than a word that also appears in the command.
- **Slow commands** make the video longer than planned. Give the scene a larger
  `hold`, or move the slow part into a hidden scene. The drift check reports how far
  off the video is.
- **Hidden scenes** run without being recorded and clear the screen afterwards, which
  makes them good for setup such as `cd`, exporting variables or warming caches.
- **The workspace** is a throwaway snapshot by default, so demos can build and write
  files without touching your checkout; see [workspace modes](container.md#workspace-modes).
