# Pronunciation

Narration keeps the real spelling of terms (`k8s`, `kubectx`), so it stays correct and
searchable. The lexicon tells the engine how to say them. See
[Pronunciation](../user-guide/voices.md#pronunciation).

**With the lexicon:**

<video controls width="100%" src="../../assets/examples/lexicon.mp4"></video>

**Without it** ("k eight z", "cube ect x"):

<video controls width="100%" src="../../assets/examples/lexicon-without.mp4"></video>

```yaml
--8<-- "examples/lexicon/lexicon.narratty.yaml:2:"
```

`kubectl` needs no entry: it is in the built-in lexicon. Put entries shared by several
specs in `narratty.lexicon.toml` in the repository or `~/.config/narratty/lexicon.toml`.

`lexicon check` lists words that may need an entry, `lexicon show` the merged entries
and where each comes from:

```console
$ narratty lexicon check examples/lexicon/lexicon.narratty.yaml
every unusual word has a lexicon entry
$ narratty lexicon show examples/lexicon/lexicon.narratty.yaml
```
