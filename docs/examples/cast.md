# Asciicast player

`--format cast` writes an asciicast, the narration as MP3 and an HTML page that plays
both. The text stays selectable, and the audio drives the player, so seeking stays in
sync.

<iframe src="../../assets/examples/cast/cast.html" width="100%" height="460" style="border: 0" title="Asciicast with narration"></iframe>

```bash
narratty build examples/cast/cast.narratty.yaml --format cast   # cast.cast, cast.mp3, cast.html
```

```yaml
--8<-- "examples/cast/cast.narratty.yaml:2:"
```

See [Asciicast with narration](../user-guide/building.md#asciicast-with-narration) to
embed the `.cast` and `.mp3` in your own page.
