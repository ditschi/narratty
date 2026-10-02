# Shell completion

narratty completes commands, options and option values in bash, zsh, fish and
PowerShell.

```bash
narratty --install-completion      # detects your shell and installs the script
narratty --show-completion zsh     # print the script, e.g. for your dotfiles
```

Besides commands, options and spec files it completes voices, providers and, for
`build --scenes`, the scene ids of the spec (also after a `,` or `:` in a range).
Restart your shell afterwards. Completion never loads voice models or starts
containers, so it stays fast; CI enforces a cold-start budget for it.
