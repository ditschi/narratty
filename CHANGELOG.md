# Changelog

All notable changes to this project are documented here. The format follows
[Conventional Commits](https://www.conventionalcommits.org/) and is maintained by
commitizen.

## Unreleased

### Feat

- project scaffold: CLI with `--version`, `doctor` and shell completion; runtime
  resolution (`auto`, `native`, `docker`, `podman`)
- spec format v1 with `init`, `validate` (line/column errors, did-you-mean hints) and
  `schema` (JSON Schema, committed as `schema/v1.json`); spec-path shell completion
- local TTS with Piper (default) and Kokoro (`narratty[kokoro]`), a curated voice
  catalog, `voices` / `voices pull`, `tts`, and a content-addressed audio cache with
  `cache info` / `cache prune`
- `build`: timeline, VHS tape, silent recording, narration track and mux into a
  narrated mp4 with a drift check; plus `plan`, `tape` and `render`
- container runtime: `--runtime docker|podman` (default when installed) runs the
  pipeline in the hardened `ghcr.io/ditschi/narratty` image (`-kokoro` variant for
  Kokoro), published to GHCR on main (`edge`) and release tags (`<version>`, `latest`)
