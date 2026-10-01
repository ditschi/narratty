#!/bin/sh
# Smoke test for the toolkit, run as any user in an image that has it in /usr/local.
set -eu
export TERM=xterm-256color HOME="${HOME:-/tmp}"
. /usr/local/share/narratty/env.sh
cd "$(mktemp -d)"
for tool in bat eza fd rg jq yazi ya file zsh tmux; do
  printf '%-5s ' "$tool"
  case $tool in tmux) tmux -V ;; *) "$tool" --version 2>&1 | head -n 1 ;; esac
done
printf 'hello\n' >file.txt
bat file.txt | grep -q hello
file -bL --mime-type file.txt | grep -q text/plain  # the magic database is found
zsh -fc 'autoload -Uz compinit && compinit -u -d "$PWD/.zcompdump" && print -r ok' | grep -q ok
# The editor layout: yazi on top, a shell below, in a terminal without terminfo files.
tmux new-session -d -s smoke -x 120 -y 30 yazi \; split-window -v -l 30% sh
sleep 2
tmux send-keys -t smoke:1.2 'echo SHELL-OK' Enter
sleep 1
tmux capture-pane -p -t smoke:1.2 | grep -q SHELL-OK
tmux capture-pane -p -t smoke:1.1 | grep -q file.txt
tmux capture-pane -p -t smoke:1.1 | grep -q hello  # preview, which needs file
tmux show -g status | grep -q off  # /usr/local/etc/tmux.conf was read
tmux kill-server
echo "toolkit ok"
