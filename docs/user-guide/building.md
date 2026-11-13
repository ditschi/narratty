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
5. **Mix.** Every clip is placed at the start of its scene as recorded, in one
   narration track, which is muxed onto the video as AAC.
6. **Check.** The result must contain video and audio, and no narration may run
   past the end of its scene by more than `--max-drift` of its length (10% by
   default). Otherwise the build exits with code 6.

After the last scene and the tail comes the end card (4 s by default; see
[`end_card`](spec.md#end_card)); `--no-end-card` leaves it out.

With `--work-dir` the tape, the silent video and the narration track are kept for
inspection.

## Scene Recording Cache

```bash
narratty build demo.narratty.yaml --scene-cache
narratty build demo.narratty.yaml --scene-cache --refresh-scene-cache
narratty cache info
narratty cache prune --scenes --older-than 30d
```

The opt-in scene cache reuses the longest unchanged prefix of the silent recording.
It replays those scenes hidden in the same shell to restore their state, records the
remaining scenes and joins the video. The last visible scene is always recorded again.
Commands and waits in reused scenes still run, so the cache saves recording work, not
the time spent running commands or waiting. A changed scene invalidates it and all
following scenes. Narration can change without invalidating the footage when its
duration and the rest of the scene timing stay the same. The cache stores only the
recordings VHS made, never a joined video, so reused scenes are re-encoded once per
build and do not lose quality over repeated builds.

The cache fingerprints the workspace files, scene inputs, timeline, narratty's own
code, the recording tools (VHS and its version, ttyd, ffmpeg, the shells, the browser
VHS launches), the installed fonts, the container image and the environment variables
that change terminal output (`TERM`, `COLORTERM`, `LANG`, `LANGUAGE`, `LC_*`, `TZ`,
`SHELL`, `PATH`, `HOME`, `NO_COLOR` and the spec's `env_passthrough`). In a git
repository, files git ignores (such as `.venv` or `node_modules`) count by size and
modification time instead of their contents; other files count by contents. The git
history itself does not count. The spec and generated output files are excluded from
the workspace fingerprint. It cannot track every external dependency: network
responses, time, files outside the workspace, symlink targets, other environment
variables, running services and commands that read the excluded files can change the
result. Replayed commands may also produce different state than the cached footage
shows. Use `--refresh-scene-cache` with `--scene-cache` to force a fresh recording
after such a change, and for final builds where reproducibility matters.

Caching currently requires at least two visible scenes and falls back to a normal
recording with drafts, fast pauses, timelapses, overlays, browser views, slides or a
project environment. It applies only to MP4 builds. Natively it also needs
`--workspace-mode rw` (or `ro`): a native snapshot gets a new directory each build,
which shows in prompts and output. In a container the snapshot is always at `/work`,
so snapshots are cached there. Sandboxed scene-cache builds use the stable container
hostname `narratty`.

Every build that records new scenes adds a recording to the cache, so it grows with
use. `narratty cache info` shows its size; `narratty cache prune --scenes --older-than 30d`
removes entries not used for that long, the recordings only they referenced and files
left by interrupted builds, and `cache prune --scenes --all` removes all scene recordings
without touching the audio cache. If the cache cannot be written (a full disk, a
read-only cache directory) the build still succeeds and logs `scene cache not updated`.

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
| `narratty plan SPEC` | Each scene's start, action time, narration length and the total, with [measured command durations](#measured-command-durations) |
| `narratty plan SPEC --draft` | The same with estimated narration lengths, without TTS |
| `narratty tape SPEC` | The generated VHS tape |
| `narratty render SPEC` | Records only the silent video (`demo.silent.mp4`) |

## How sync works

Narration starts when its scene starts, so the voice talks while the command is
typed. Set `narration_start: after_actions` on a scene to speak only after its
actions. The pause that fills a scene goes after its actions; at a `hold: auto` the
scene waits until the narration and `timing.narration_buffer_ms` are done, so what
follows starts after the voice has finished (before 0.7 it only waited for what the
actions after it did not fill).

The recording notes where each scene really started, and for `after_actions` where
its actions really ended. Each clip is placed there, so a command that takes longer
than planned moves only its own scene's narration; later scenes stay in sync, and
`hold: auto` (explain, then run) and `after_actions` (run, then explain) keep their
order. Subtitles follow the clips; overlays, headings, slides, table rows and Mermaid
focus follow the moments they were recorded at.

A longer scene only adds a pause, so the drift check does not compare the video's
length with the plan. It fails when a narration runs into the next scene, and names
the scene and why, e.g. `intro (0.80s over: scene recorded 0.80s shorter than
planned)`. Shorter narration overruns are logged as warnings. The CLI still prints
the video's and the plan's length.

When VHS writes no scene markers, the planned clip positions are stretched to the
video's length instead.

### Dropped frames

VHS takes frames in real time. On a busy machine it misses some, and the video comes
out shorter than the time it recorded, so everything on screen happens too early.
narratty compares the two right after recording. When the video is more than 3% (and
at least half a second) short, it logs a warning naming both lengths and stretches
the recording back to real time, repeating frames, before anything is placed on it.
Typing then looks a little less smooth, but the narration matches. Build on a quieter
machine for the best picture.

### Measured command durations

The plan counts a `run` as its typing plus `timing.run_hold_ms`; it cannot know that
`make` takes twelve seconds. [`narratty check`](commands.md) runs every command anyway
and notes how long each took, from Enter until the shell was back:

```console
$ narratty check demo.narratty.yaml
recorded how long 6 commands took; plans now wait for the slow ones: build (12.3s)
```

`plan`, `tape` and `build` then pause after such a command until it is done (plus
0.3 s), so its output is on screen before the scene goes on, the narration's fill
shrinks accordingly, and `plan` shows realistic lengths. They log the commands they
wait for, and `plan` lists the scenes that use measurements.

- Measurements are kept in the [cache directory](voices.md#audio-cache)
  (`command-durations.json`), keyed by the spec's title, the shell, the layout, the
  scene and the command. Changing a command forgets its measurement; run `check`
  again to update them.
- A command stopped with a control key (`C-c`) or still running at the end is not
  measured. A `wait` needs no measurement: it blocks until the output is there.
- With job control off (`set +m`), commands are only measured on Linux.
- `timing.measured_durations: false` plans with `run_hold_ms` only, e.g. for builds
  that must not depend on an earlier `check`.

## Things to know

- **`wait` matches the whole screen**, including the command you just typed. Wait for
  text that only the command's output contains, e.g. `wait: {screen: "Build
  succeeded"}` rather than a word that also appears in the command.
- **Slow commands** make their scene longer than planned, but only that scene. Run
  `narratty check` first, so the plan [waits for them](#measured-command-durations), or
  move the slow part into a hidden scene.
- **A video shorter than planned** means VHS dropped frames, usually because the
  machine was busy. narratty stretches the recording back to real time and warns; if
  the drift check still fails, the error shows the load average. Build again when the
  machine is idle.
- **Hidden scenes** run without being recorded and clear the screen afterwards, which
  makes them good for setup such as `cd`, exporting variables or warming caches.
- **The workspace** is a throwaway snapshot by default, so demos can build and write
  files without touching your checkout; see [workspace modes](container.md#workspace-modes).
