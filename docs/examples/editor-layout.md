# Editor layout

`terminal.layout: editor`: `yazi` as explorer and preview on top, a shell below, in one
`tmux` window. `focus` and `reveal` move between the panes, `diff` shows what the demo
changed. See [Editor layout](../user-guide/toolkit.md#editor-layout) for the details.

<video controls width="100%" src="../../assets/examples/editor-layout.mp4"></video>

```yaml
terminal:
  layout: editor
scenes:
  - id: explore
    narration: Switch to the explorer and open the source folder.
    pause_ms: 600ms
    actions:
      - focus: explorer
      - key: Right
      - key: Right
      - key: Down
  - id: run
    narration: Back in the terminal, run the program.
    actions:
      - focus: terminal
      - run: PYTHONPATH=src python3 -m greet Ada Grace
      - wait: "Hello, Grace!"
  - id: diff
    narration: Finally, the diff shows everything this demo changed.
    actions:
      - diff
```

```bash
narratty build examples/editor-layout/editor.narratty.yaml
```
