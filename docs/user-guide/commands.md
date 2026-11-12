# Commands

`SPEC` is a `.narratty.yaml` file or, since 0.6, a Markdown doc built on its own with
the spec it implies (see [Building a doc on its own](markdown.md#building-a-doc-on-its-own)).

| Command | Does |
|---|---|
| `narratty init [FILE] [--force]` | Write a commented starter spec (default `demo.narratty.yaml`) |
| `narratty init --markdown DOC [FILE]` | Write a spec that makes the video from `DOC` (default `<doc>.narratty.yaml`) (since 0.6) |
| `narratty validate SPEC` | Check a spec; report every problem, and hints for redundant lines, with line and column |
| `narratty schema` | Print the spec's JSON Schema |
| `narratty compile SPEC [-o FILE]` | Print the spec with its [Markdown entries](markdown.md) expanded (since 0.5) |
| `narratty compile SPEC --fingerprint` | Print a hash of what the video shows and says, to notice when a committed video is outdated (since 0.5) |
| `narratty voices [--provider P] [--installed]` | List curated and installed voices |
| `narratty voices pull VOICE` | Download a voice (and the Kokoro model) |
| `narratty tts SPEC [--offline]` | Synthesize all narration clips and print their lengths |
| `narratty lexicon show SPEC` | List the [pronunciation lexicon](voices.md#pronunciation) entries and where each comes from |
| `narratty lexicon check SPEC` | List narration words that look hard to pronounce and have no entry |
| `narratty cache info` / `prune [--older-than 30d] [--all]` | Inspect or prune the audio cache |
| `narratty plan SPEC [--draft]` | Print the timeline and total length |
| `narratty plan SPEC --sources` | List where each scene comes from (Markdown file and line) and what was left out (since 0.5) |
| `narratty tape SPEC [-o VIDEO]` | Print the VHS tape |
| `narratty render SPEC [-o VIDEO]` | Record the silent video |
| `narratty build SPEC [-o VIDEO] [--work-dir DIR] [--max-drift 0.10]` | Build the narrated video |
| `narratty build SPEC --subtitles MODE` | Add [subtitles](building.md#subtitles): `none`, `files`, `track` or `burn` |
| `narratty build SPEC --draft` | Build a fast [draft](building.md#draft) (`demo.draft.mp4`) |
| `narratty build SPEC --fast` | Fill long pauses with still frames instead of recording them ([fast pauses](building.md#fast-pauses)) |
| `narratty build SPEC --ignore-exit` | Don't check exit codes, except where the spec sets `expect_exit` ([exit codes](spec.md#exit-codes)) |
| `narratty build SPEC --format cast [-o PAGE]` | Build an [asciicast with narration](building.md#asciicast-with-narration) |
| `narratty check SPEC` | Run the commands without recording; check their exit codes and [output](spec.md#expected-output) (since 0.6) |
| `narratty env shell SPEC` | Open a shell in the spec's [project environment](environments.md) |
| `narratty env build SPEC [--rebuild-env]` | Build the environment's image and print its tag |
| `narratty env up SPEC` | Start the environment and keep it; `build`, `render` and `env shell` reuse it |
| `narratty env down SPEC` | Remove what `env up` started |

`plan`, `tape`, `render` and `build` take `--end-card` / `--no-end-card` to override
[`end_card`](spec.md#end_card). `build`, `render` and `check` also take `--workspace-mode`,
`--keep-workspace`, `--allow-dirty`, `--network`, `--allow-host` and `--yes`; see
[Sandboxed runs](container.md). They take `--env-image`, `--no-env`, `--keep-env` and `--rebuild-env` for
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
| 7 | a recorded command exited contrary to its `expect_exit` |
| 8 | a command printed other output than its `expect_output` (`narratty check`) |
