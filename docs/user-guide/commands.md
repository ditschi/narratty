# Commands

| Command | Does |
|---|---|
| `narratty init [FILE] [--force]` | Write a commented starter spec (default `demo.narratty.yaml`) |
| `narratty validate SPEC` | Check a spec and report every problem with line and column |
| `narratty schema` | Print the spec's JSON Schema |
| `narratty voices [--provider P] [--installed]` | List curated and installed voices |
| `narratty voices pull VOICE` | Download a voice (and the Kokoro model) |
| `narratty tts SPEC [--offline]` | Synthesize all narration clips and print their lengths |
| `narratty lexicon show SPEC` | List the [pronunciation lexicon](voices.md#pronunciation) entries and where each comes from |
| `narratty lexicon check SPEC` | List narration words that look hard to pronounce and have no entry |
| `narratty cache info` / `prune [--older-than 30d] [--all]` | Inspect or prune the audio cache |
| `narratty plan SPEC [--draft]` | Print the timeline and total length |
| `narratty tape SPEC [-o VIDEO]` | Print the VHS tape |
| `narratty render SPEC [-o VIDEO]` | Record the silent video |
| `narratty build SPEC [-o VIDEO] [--work-dir DIR] [--max-drift 0.10]` | Build the narrated video |
| `narratty build SPEC --subtitles MODE` | Add [subtitles](building.md#subtitles): `none`, `files`, `track` or `burn` |
| `narratty build SPEC --draft` | Build a fast [draft](building.md#draft) (`demo.draft.mp4`) |
| `narratty build SPEC --format cast [-o PAGE]` | Build an [asciicast with narration](building.md#asciicast-with-narration) |
| `narratty env shell SPEC` | Open a shell in the spec's [project environment](environments.md) |

`plan`, `tape`, `render` and `build` take `--end-card` / `--no-end-card` to override
[`end_card`](spec.md#end_card). `build` and `render` also take `--workspace-mode`,
`--keep-workspace`, `--allow-dirty`, `--network`, `--allow-host` and `--yes`; see
[Sandboxed runs](container.md). They take `--env-image`, `--no-env` and `--keep-env` for
[project environments](environments.md). Every command that runs the pipeline takes
`--runtime` and `--image`.

| Command | Does |
|---|---|
| `narratty doctor [--runtime R]` | Check the tools the selected runtime needs |
| `narratty --version` | Print the version |
| `narratty --install-completion` | Install shell completion |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | unexpected error |
| 2 | usage error |
| 3 | spec validation error |
| 4 | missing dependency (tool, voice or container runtime) |
| 5 | render or mux failure |
| 6 | sync verification failure |
