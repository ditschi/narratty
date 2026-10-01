# Changelog

All notable changes to this project are documented here. The format follows
[Conventional Commits](https://www.conventionalcommits.org/) and is maintained by
commitizen.

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
