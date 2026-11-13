# Changelog

All notable changes to this project are documented here. The format follows
[Conventional Commits](https://www.conventionalcommits.org/) and is maintained by
commitizen.

## v0.7.0 (2026-11-13)

### Feat

- **sync**: plan with command durations measured by check
- **sync**: place narration per scene from recorded markers
- **markdown**: hold keeps a slide up for the text after it
- **markdown**: clear comment and clear_on
- **markdown**: run comment for narration order, substitutes, output lines and long-running commands
- **markdown**: no-run blocks stay on screen without ^C
- **spec**: show one command and run another, cut long output
- **markdown**: warn about likely authoring problems in validate
- **slides**: focus sequence diagram participants
- **markdown**: better defaults for common Markdown
- **slides**: add syntax-highlighted code slides
- add opt-in scene recording cache
- **markdown**: reuse Mermaid diagrams for focus steps
- **walkthrough**: sync narration with table and Mermaid focus

### Fix

- **container**: remove the container and snapshot when a build is interrupted
- **container**: warn about an image with another narratty, and name host paths in its errors
- **build**: stop before native hidden commands that change your home directory
- **check**: measure command durations when job control is off
- **timeline**: let hold: auto wait for the whole narration
- **check**: keep hidden commands out of the measured durations file
- **hints**: name a command that was not found, and speak Markdown in hints for docs
- **overlays**: keep the title card up while a doc's intro is spoken
- **markdown**: do not clear the screen at headings before the first visible scene
- **validate**: sharpen the Markdown warnings
- **markdown**: read overlay comment text with a colon as text, and drop the schema hint for doc errors
- **check**: count no-run commands as shown only and warn when none ran
- **markdown**: speak an inline footnote after its sentence when the marker follows the full stop
- **markdown**: keep the next block's lead-in out of the text after a slide
- **sync**: lengthen a pause only for commands that outlast it
- **sync**: judge only real clips, ignore VHS start-up overhead
- **render**: let check see zsh's prompt after its PROMPT_SP redraw
- **render**: suggest redirecting background output in the prompt timeout hint
- **ui**: print errors without turning `:x:` in image tags into emoji
- **spec**: hint at quoting for YAML that does not parse, not at the schema
- **build**: log what is captured in Chromium instead of always "browser views"
- **container**: print the host path of the output, not /out/...
- **build**: blame dropped frames, not slow commands, when the video is short
- **environment**: say why a native run still starts the environment
- **container**: announce image pulls, wrap pull failures, keep plan --draft on the host
- **render**: find the prompt after output without a newline; name the scene on timeouts
- **container**: remove the compiled spec with hidden commands after the run
- **exits**: keep hidden-scene clears and secrets out of exit attribution
- **workspace**: retry the snapshot clone without hard links across filesystems
- **markdown**: no prompt warning for doc examples, "and above" is not spatial
- **markdown**: report one error for a wrong sections value
- **cache**: count and prune leftovers of interrupted scene writes
- **cache**: skip the scene cache for native workspace snapshots
- **cache**: keep builds and hits working when the cache is not writable
- **cache**: never re-cache joined footage
- **cache**: key footage to an environment allowlist, not git HEAD
- **cache**: key scene footage to VHS, fonts, browser and image
- **markdown**: tie focus comments to the diagram on screen
- **spec**: check that table rows match the header
- **render**: keep slide images inside the workspace
- **render**: match Mermaid focus IDs exactly
- **render**: outline nested Mermaid shapes in focus
- **check**: match long expected output without recursion
- support varied frame rates and Mermaid focus IDs
- **render**: match Mermaid focus target ordinals

### Refactor

- **markdown**: move lint_entry into lint to break an import cycle
- move host_path to narratty.paths to break an import cycle
- **markdown**: split block dispatch and option parsing

### Perf

- **cache**: fingerprint git-ignored workspace files by metadata

### Behaviour change

- Markdown input (spec `version: 1`):
  - Warning, caution, danger and important admonitions now start with their type and
    title when spoken. Set `admonitions: false` in the `markdown` entry for the old reading.
    Remove workarounds such as `<!-- narratty: say Warning! -->`, which now double up.
  - An image's alt text becomes its slide title. Set `image_titles: false` to turn this off.
  - A paragraph ending in ":" right before a `table` comment is spoken while the slide is
    shown.
  - Footnote markers and definitions, and task-list boxes, are no longer spoken. Use
    `footnotes: inline` to speak footnotes after their sentence.
  - `no-run` blocks keep the command on screen without the `^C`.
- Narration is placed per scene from the recorded markers instead of being stretched
  linearly over the whole video, and the drift check judges each scene.
- `hold: auto` (and `say: before`) waits for the whole narration plus
  `timing.narration_buffer_ms`. Scenes that used it mid-scene get longer.
- After `narratty check`, `plan` and `build` wait for slow commands using the measured
  durations. Set `timing.measured_durations: false` to plan with `run_hold_ms` only.
- `--runtime native` refuses hidden commands that use `--global`, `~` or `$HOME` unless
  `--yes` is given.
- Scene-cache entries from 0.6 are not reused.

## v0.6.1 (2026-11-12)

### Fix

- bound overlay inputs to visible intervals

## v0.6.0 (2026-11-12)

### Feat

- build Markdown docs directly, init --markdown and narratty check
- **spec**: slides, tables, pauses and Mermaid diagrams

### Behaviour change

- Markdown input (spec `version: 1`): an image on a line of its own is now shown as a
  slide instead of in a browser view, and `mermaid` blocks, left out before, are now
  drawn as slides. `images: false` in the `markdown` entry leaves out both, as does a
  `<!-- narratty: skip -->` comment for a single image or block; the browser view for
  images is gone.

## v0.5.0 (2026-11-12)

### Feat

- **spec**: browser comments open a marked link of Markdown input
- **spec**: leave the heading out of scene ids when it repeats the file stem
- **spec**: show images of Markdown input in a browser view
- **cli**: narratty compile and plan --sources for Markdown input
- **spec**: commands, files, doc comments and overrides in Markdown input
- **render**: chapter overlays hide after 3s; overlay_styles: {chapter: {keep: true}} keeps them
- **spec**: expand Markdown docs into scenes
- **spec**: accept markdown entries in scenes
- **spec**: requires.narratty and the spec versioning rule

### Fix

- **container**: run as container root under rootless Docker
- **container**: resolve the workspace from the spec, not its compiled copy

## v0.4.1 (2026-10-01)

### Fix

- **render**: keep VHS waits for helper messages working after the screen scrolled
- **render**: start VHS with bash in the editor bridge and for sh

## v0.4.0 (2026-10-01)

### Feat

- **environment**: editor layout and diff in project environments
- **end-card**: show the logo above the text

## v0.3.0 (2026-10-01)

### Feat

- per-scene fast, per-command expect_exit, --ignore-exit, exit codes in environments
- record in the project's dev container (via its Compose file); wait until a command has finished
- run demos in a Compose service or a running container
- add demo packages to the environment (environment.packages)
- run the demo shell in a project image (environment.image)
- **build**: add --fast to fill long pauses with still frames
- **scenes**: browser action shows a web page in the video
- text overlays for chapter titles, file names and notes
- **toolkit**: add file so yazi shows previews
- **scenes**: check the exit codes of recorded commands
- **spec**: pause after key presses (timing.pause_ms, scene pause_ms)
- **spec**: key: Enter, duration strings and validate hints
- **spec**: run action, wait shorthand and schema that accepts `- enter`
- **sandbox**: sandbox.docker gives the demo the host's container engine
- **scenes**: per-scene timelapse shows long steps sped up
- subtitles from the narration and --draft builds
- **tts**: pronunciation lexicon
- editor layout with focus, reveal and diff actions

### Fix

- env shell reports a spec without environment before looking for Docker
- **browser**: stop Chromium's helper processes before removing the profile
- **browser**: allow a slow first Chromium start and drop its stderr
- **exits**: log bash 3.2 commands from history
- keep the terminal size in --draft builds
- reject Home and End keys, which VHS cannot press

### Refactor

- **environment**: keep image, compose and container as sources
- **exits**: read typed lines from the recording script

### Perf

- **tts**: synthesize Piper clips in parallel and log uncached clips

## v0.2.0 (2026-09-30)

### Feat

- **tts**: make Kokoro with its fp16 model the default voice
- **toolkit**: publish static demo tools as the narratty-toolkit image
- **build**: add --format cast: asciicast, MP3 narration and player page

## v0.1.0 (2026-09-30)

### Feat

- **end-card**: close videos with a "Created with narratty" card and QR code
- **sandbox**: add workspace modes, network allowlist and sandbox consent
- **container**: add the narratty image, GHCR publishing and a container runtime
- **build**: render narrated videos with VHS and ffmpeg
- **tts**: add Piper and Kokoro providers with voice catalog and audio cache
- **init**: point the schema header at the installed version's schema
- **spec**: add spec format v1 with init, validate and schema commands
- project scaffold with doctor command and shell completion

### Fix

- **container**: install ttyd from its release binary
