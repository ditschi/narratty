# End card

Every video ends with a 4 s card: "Created with narratty", a link to these docs and a
QR code of the link.

<video controls width="100%" src="../../assets/examples/end-card.mp4"></video>

To leave it out:

| Scope | Setting |
|---|---|
| One build | `narratty build demo.narratty.yaml --no-end-card` |
| One spec | `end_card: false` |
| All your builds | `[end_card]` `enabled = false` in `~/.config/narratty/config.toml` |

`end_card.duration_ms` sets the length, `end_card.qr: false` drops the QR code. See
[`end_card`](../user-guide/spec.md#end_card).
