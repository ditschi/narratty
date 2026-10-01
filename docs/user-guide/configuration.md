# Configuration

## Files

| Path | Holds |
|---|---|
| `~/.config/narratty/config.toml` | Your defaults and limits (below) |
| `~/.config/narratty/lexicon.toml` | Your [pronunciation](voices.md#pronunciation) entries |
| `~/.config/narratty/approvals.json` | Sandbox permissions you approved, per spec |
| `~/.local/share/narratty/` | Downloaded voices and models |
| `~/.cache/narratty/` | Audio cache, workspace snapshots, build caches |

Paths follow the platform's conventions (on macOS under `~/Library`).

## `config.toml`

```toml
[end_card]
enabled = false                    # no closing card unless a spec or flag asks for it

[sandbox]
max_network = "allowlist"          # none | allowlist | full
allow_env = ["LM_LICENSE_FILE"]    # env_passthrough names a spec may use
allow_mounts = true
allow_ssh_agent = false
```

Every key is optional. A command-line flag beats the spec, and the spec beats this
file. `[sandbox]` is a cap: a spec asking for more fails. See
[Sandboxed runs](container.md#sandbox-permissions).

## Environment variables

| Variable | Effect |
|---|---|
| `NARRATTY_RUNTIME` | `auto`, `native`, `docker` or `podman` (same as `--runtime`) |
| `NARRATTY_IMAGE` | Container image (same as `--image`) |
| `NARRATTY_OFFLINE` | `1`: never download voices (same as `--offline`) |
| `NARRATTY_YES` | `1`: approve sandbox permissions without asking (same as `--yes`) |
| `NARRATTY_CONFIG_DIR` | Directory of `config.toml` and `approvals.json` |
| `NARRATTY_DATA_DIR` | Directory for voices and models |
| `NARRATTY_CACHE_DIR` | Directory for caches |
| `NO_COLOR` | Plain output |
