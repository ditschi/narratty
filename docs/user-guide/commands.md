# Commands

| Command | Does |
|---|---|
| `narratty init [FILE] [--force]` | Write a commented starter spec (default `demo.narratty.yaml`) |
| `narratty validate SPEC` | Check a spec and report every problem with line and column |
| `narratty schema` | Print the spec's JSON Schema |
| `narratty voices [--provider P] [--installed]` | List curated and installed voices |
| `narratty voices pull VOICE` | Download a voice (and the Kokoro model) |
| `narratty tts SPEC [--offline]` | Synthesize all narration clips and print their lengths |
| `narratty cache info` / `prune [--older-than 30d] [--all]` | Inspect or prune the audio cache |
| `narratty doctor [--runtime R]` | Check the tools the selected runtime needs |
| `narratty --version` | Print the version |
| `narratty --install-completion` | Install shell completion |

More commands (`tape`, `render`, `build`, …) arrive with the next milestones;
see the [design](../design.md#cli-surface).

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
