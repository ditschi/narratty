# Terminal look

The `terminal` block sets the video size, font size, [VHS theme](https://github.com/charmbracelet/vhs/blob/main/THEMES.md),
prompt and typing speed. See [`terminal`](../user-guide/spec.md#terminal).

<video controls width="100%" src="../../assets/examples/terminal-look.mp4"></video>

```yaml
--8<-- "examples/terminal-look/terminal-look.narratty.yaml:2:"
```

- `shell: zsh` (or `fish`, `sh`) records another shell.
- A scene's own `typing_speed_ms` overrides the global one.
