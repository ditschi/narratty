# Editor layout

A layout like an editor: `yazi` as explorer and preview on top, a shell below, in one
`tmux` window. `tmux` and `yazi` come from the [demo toolkit](../user-guide/toolkit.md),
which the narratty image contains.

<video controls width="100%" src="../../assets/examples/editor-layout.mp4"></video>

A hidden first scene builds the layout:

```yaml
- id: layout
  hidden: true
  actions:
    - type_command: >-
        tmux new-session -s ide yazi \;
        split-window -v -l 30% "PS1='$ ' bash --norc" \;
        select-pane -t 1 -T Explorer \; select-pane -t 2 -T Terminal
    - enter
    - wait: {screen: "Terminal"}
```

The scenes after it press `Ctrl+b` and an arrow key to move between the panes
(`ctrl_sequence: C-b`, `key: Up`) and use the arrow keys in the explorer. A hidden last
scene runs `tmux kill-server`, so the end card gets the whole terminal.

```bash
narratty build examples/editor-layout/editor.narratty.yaml
```

