# Changelog

All notable changes to this project are documented here. The format follows
[Conventional Commits](https://www.conventionalcommits.org/) and is maintained by
commitizen.

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
