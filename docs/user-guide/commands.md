# Commands

| Command | Does |
|---|---|
| `narratty doctor [--runtime R]` | Check the tools the selected runtime needs |
| `narratty --version` | Print the version |
| `narratty --install-completion` | Install shell completion |

More commands (`validate`, `tts`, `render`, `build`, …) arrive with the next milestones;
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
