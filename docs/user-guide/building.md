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

With `--work-dir` the tape, the silent video and the narration track are kept for
inspection.

## Looking before rendering

| Command | Shows |
|---|---|
| `narratty plan SPEC` | Each scene's start, action time, narration length and the total |
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
- **The workspace** is used in place for now, also when the build runs in a
  [container](container.md).
