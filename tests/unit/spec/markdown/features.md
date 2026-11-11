# Features

<!-- narratty: hidden
mkdir -p demo && cd demo
-->

Shell blocks split where the shell would run a command.

```bash
# set up
export NAME=demo  # not typed
cat > hello.txt <<'EOF'
Hello # kept, it is in the heredoc
EOF
if [ -f hello.txt ]; then
  echo found
fi
```

## Files

Write a file and show it.

```yaml title="config/demo.yaml"
name: demo
```

```yaml {#quiet title="quiet.yaml" narratty="hidden"}
quiet: true
```

## Options and comments

<!-- narratty: skip -->
This paragraph is only for readers.

<!-- narratty: say
The video says this instead.
-->

<!-- narratty: overlay {text: Note, style: file} -->

```console {#typed narratty="no-run"}
$ narratty build "$SPEC"
```

```console {#fails narratty="expect-failure"}
$ false  # fails on purpose
```

<!-- an ordinary comment -->

### Deeper

Deeper text.
