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

A build records only what changed: scenes recorded before are taken from a
[cache](#faster-rebuilds), and `--scenes` builds just the part you are working on.

## Faster rebuilds

While you write a video you change a word of narration, fix a command, move an
overlay and build again. VHS records in real time, so recording the whole video each
time is the slow part. `narratty build` therefore records every scene on its own and
keeps the recordings in the cache (`narratty cache info`). A scene is recorded again
only when something that changes its picture changed:

| You change | Recorded again |
|---|---|
| Narration, voice, lexicon, overlays, browser views, subtitles, end card text | Nothing, with [`--fast` or `--draft`](#fast-pauses) (the pauses are stretched to the new length). Without them, the scenes whose pause changed |
| A command, `wait`, `hold`, `typing_speed_ms`, `fast`, `timelapse` of one scene | That scene and the ones after it |
| `terminal`, `workspace`, `sandbox`, `environment`, `--draft`, a new narratty or VHS version | Everything |

Later scenes are recorded again because their screen and shell state (directory,
variables, files) depend on the earlier ones. The video is the same as a clean build
would give; only the work is skipped. `narratty plan SPEC` shows in its `recording`
column which scenes the next build takes from the cache.

```bash
narratty build demo.narratty.yaml --draft --fast   # the loop while you write
narratty build demo.narratty.yaml --clean          # the final, exact video
```

`--clean` ignores the cache and records everything in one run (and refreshes the
cache). Use it for the release video, and whenever a video looks wrong: the cache
does not know that a file in your repository changed. List the files whose content
matters in [`cache.inputs`](spec.md#cache), and a change to one re-records
everything.

### Scene ranges

```bash
narratty build demo.narratty.yaml --scenes clone                  # one scene
narratty build demo.narratty.yaml --scenes clone:open-vscode      # these and everything between
narratty build demo.narratty.yaml -s :clone,wrap-up:              # the first scenes and the last ones
```

`--scenes` (`-s`) takes scene ids, `FROM:TO` ranges (both included), `FROM:` (to the
end) and `:TO` (from the start), comma-separated or repeated; the shell completes the
ids. The video holds only those scenes and is written to `demo.scenes.mp4` (or
`demo.scenes.draft.mp4`). It starts with the lead-in only when it starts with the first
scene, and ends with the tail and end card only when it ends with the last.

The scenes before the range still have to run, so the shell is in the state they
leave it in. They run unrecorded and quickly: typing is nearly instant and long pauses
are cut to a second. If a command is still running when such a pause ends, narratty
notes it, builds again and from then on replays that scene at its own pace. Set
`replay: realtime` on a scene to do so from the start, for example for a program that
needs time between keys.

The recordings of a range go into the cache, so the next full build only records
the scenes the range did not cover. `--scenes` also works with `--format cast`; that
has no cache.

### Watching

```bash
narratty build demo.narratty.yaml --draft --fast --watch --scenes clone:cloned
```

`--watch` (`-w`) builds, then builds again whenever the spec, its lexicon files,
`cache.inputs` files or a local page shown in a browser view change. A change made
while a build runs starts the next build when it ends. A build that fails is reported
and waited out; Ctrl+C stops.

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
- long pauses are [fast](#fast-pauses); one that does not end on a still screen is
  logged, not an error;
- the video is silent and the narration is burned in as subtitles, so you see
  where each line would be spoken (`--subtitles` picks another mode).

`narratty plan SPEC --draft` prints the estimated timeline. `--draft` only applies to
mp4 output.

## Fast pauses

```bash
narratty build demo.narratty.yaml --fast
```

Most of a narrated video is pauses: the screen holds still while the voice talks.
VHS records in real time, so a 10 s pause costs 10 s of recording. With `--fast`, a
visible pause longer than 1 s is recorded for 1 s, and its last frame is repeated for
the rest. The video is as long as without `--fast`; the cursor does not blink.

That is only right when the screen is still at the end of that second, so narratty
checks the recording and fails, naming the scene, when

- the screen changed in the last half second, or
- a command the scene started is still running (it might print later). Interactive
  programs (editors, pagers, tmux) do not count; they wait for keys.

For a command that runs longer, add a `wait` for its last output before the pause, or
set `fast: false` on the scene. The running-command check reads `/proc`, so it only works on
Linux (natively or in the container). In the editor layout it only sees `tmux`, so
there only the screen is checked. Pauses in [timelapse](spec.md#timelapse) scenes are
recorded in full; those scenes are sped up anyway.

A scene's `fast` overrides the command line: `fast: false` records its pauses in full
even with `--fast`, `fast: true` fills them even without it.

```yaml
scenes:
  - id: build
    fast: false        # output may still arrive during the pause
    actions:
      - run: make
```

With `--format cast`, `--fast` skips the rest of a pause once there has been no
output for half a second and no command is running. The cast's timestamps are the
same as without it.

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
  `.cast` itself has none: asciicast has no way to store them. The same goes for
  browser views, which the page shows as images over the player.
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
| `narratty plan SPEC` | Each scene's start, action time, narration length, the total and whether the next build records the scene or takes it from the cache |
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
  off the video is; it only fails when the difference is also more than 250 ms, so
  a one-scene range is not rejected for a few frames.
- **Hidden scenes** run without being recorded and clear the screen afterwards, which
  makes them good for setup such as `cd`, exporting variables or warming caches.
- **The workspace** is a throwaway snapshot by default, so demos can build and write
  files without touching your checkout; see [workspace modes](container.md#workspace-modes).
