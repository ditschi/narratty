# Slides and themes

Since narratty 0.8.

A doc that explains more than it runs: a list, a diagram and one command. With
[`prose: slides`](../user-guide/markdown.md#prose-slides) its paragraphs show their key
points and the list its items; a [theme](../user-guide/spec.md#themes) of its own
restyles every slide, the terminal takes the same colours, and the
[frame](../user-guide/spec.md#frame) keeps the section heading at the top.

<video controls width="100%" src="../../assets/examples/slides.mp4"></video>

The spec turns it all on:

```yaml
--8<-- "examples/slides/slides.narratty.yaml:3:"
```

The theme is plain CSS for the slide's `section`, its `h1` and its content. Rules it
leaves out keep the built-in look; a [Marp](https://marp.app) theme works the same way:

```css
--8<-- "examples/slides/theme.css"
```

The doc is ordinary Markdown, with nothing written for the video alone:

````markdown
--8<-- "examples/slides/pipeline.md"
````

- `narratty plan --sources examples/slides/slides.narratty.yaml` lists the key point of
  each paragraph.
- Without `slides.css`, the slides keep the built-in `dark` look, which takes the
  terminal's background.
