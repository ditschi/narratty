# Web pages

A `browser` action shows a web page or a local HTML file in the video. Headless
Chromium (in the narratty image) captures it once and scrolls it. See
[Browser views](../user-guide/spec.md#browser-views).

<video controls width="100%" src="../../assets/examples/browser.mp4"></video>

```yaml
--8<-- "examples/browser/browser.narratty.yaml:2:"
```

- `scroll: auto` scrolls to the end of the page (at most 4 screens).
- Local files (`site/index.html`) need no network.
- To browse inside the terminal instead, run a text browser such as `w3m` or `lynx`,
  or `glow` for Markdown. They are not in the image; add them with
  [`environment.packages`](../user-guide/environments.md#extra-tools-for-the-demo).
