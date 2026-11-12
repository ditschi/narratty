# Markdown input

Since narratty 0.5.

A Markdown doc can be the source of a video, so one file is both read and watched.
Paragraphs become the narration, code blocks become what the video types and runs.
Plain docs need no extra markup. Comments and code block attributes, both invisible
on the rendered page, change what the video does where the defaults don't fit.

The video is made from this page; its spec is
[`examples/markdown/markdown.narratty.yaml`](https://github.com/ditschi/narratty/blob/main/examples/markdown/markdown.narratty.yaml).

<video controls width="100%" src="../../assets/examples/markdown.mp4"></video>

## Quick start

Write the doc as usual. This one says hello in the terminal.

````markdown title="hello.md"
# Hello

Say hello to the terminal.

```console
$ echo "Hello from Markdown"
```
````

A spec points at the doc with a `markdown` entry in its scenes. The entry turns into
ordinary scenes, so hand-written scenes can stand before and after it.

```yaml title="hello.narratty.yaml"
scenes:
  - markdown: hello.md
```

`narratty compile` prints the scenes the doc turns into. The paragraph is the
narration, and the console line is a command that runs.

```console
$ narratty compile hello.narratty.yaml
```

`narratty plan --sources` lists where each scene comes from, and what was left out
and why.

```console
$ narratty plan --sources hello.narratty.yaml
```

<!-- narratty: skip -->
Build the video like any other spec:

<!-- narratty: say
The video is built like any other spec. Here the command is only typed, not run.
-->

```console {narratty="no-run"}
$ narratty build hello.narratty.yaml
```

## How a doc becomes scenes

The doc is read in order. Paragraphs collect until a code block runs; then they are
the narration of the scene that runs it.

| Markdown | In the video |
|---|---|
| Paragraphs before a code block, same section | The narration of the scene that runs the block |
| Paragraphs after the last block of a section | A scene without actions; the output stays on screen |
| A block without a paragraph before it | A silent scene |
| `console` block | `$ ` lines run, `> ` lines continue them; other lines are output and not typed |
| `bash` / `sh` block | Each complete command runs (heredocs, `if`, `for` stay together); `# …` comments are not typed |
| Other language with a `title` | Written to that file (hidden), then shown with `cat` and a file overlay |
| Other language without a `title` | Left out |
| Inline code, links, emphasis | Read as plain text |
| List items | Read as sentences; a code block in an item runs like any other |
| Quotes and GitHub alerts (`> [!NOTE]`) | Read like paragraphs, without the `[!NOTE]` marker |
| Admonitions `!!!` and open collapsible blocks `???+` | Read without their title; code blocks inside run as usual |
| Collapsed blocks `???` and `<details>` | Left out, with everything inside |
| Content tabs `=== "…"` | One tab per tab set, see [below](#callouts-and-tabs) |
| An image on a line of its own | Shown in a [browser view](spec.md#browser-views) while the text around it is spoken, see [Images](#images) |
| Tables, images within text, raw HTML | Left out |

Every command waits until the prompt is back, so the next one starts after it has
finished. A command that fails stops the build, as in a YAML spec; mark the block
`expect-failure` when that is the point (see [Code block attributes](#code-block-attributes)).

Scene ids are `<file stem>-<heading>-<n>`, for example `install-uv-2`; a heading
whose slug is the file stem is left out (`install-1`, not `install-install-1`). A
block with an id uses `<file stem>-<id>`, which survives edits around it.
`id_prefix` replaces the file stem.

## Callouts and tabs

Admonitions are spoken without their title, so a tip reads as part of the text.

!!! tip "Short paragraphs"
    Keep paragraphs short. Each one is a sentence or two of narration.

Collapsed blocks are for readers only. The video leaves them out, with everything
inside, including code blocks.

??? note "Only on the page"
    This text and the command below are not part of the video.

    ```console
    $ echo "only for readers"
    ```

This is how both look in the doc.

````markdown title="callouts.md"
!!! tip "Short paragraphs"
    Keep paragraphs short. Each one is a sentence or two of narration.

??? note "Only on the page"
    This text and the command below are not part of the video.
````

Content tabs show one tab in the video: the first, or the first label the entry
lists in `tabs`. This video picks the bash tab.

=== "zsh"

    ```console
    $ echo "$ZSH_VERSION"
    ```

=== "bash"

    ```console
    $ echo "$BASH_VERSION"
    ```

Collapsible blocks that start open are spoken like admonitions. HTML `details` blocks
are left out like collapsed ones.

## Images

An image on a line of its own is shown while the text around it is spoken.

![Overlays in a narratty video: a chapter title, a file name and a note](../assets/overlays.png)

The image stays until the next command or heading, so it never covers what is typed.
It is embedded in the spec, which keeps it working in the sandbox without network.

Images within a sentence, remote images and formats other than PNG, JPEG, GIF, SVG
and WebP are left out. `images: false` in the entry leaves out all images, and a
`skip` comment a single one.

## Doc comments

HTML comments are invisible on the docs site and on GitHub. Those starting with
`narratty:` hold what only the video needs:

```markdown
<!-- narratty: skip -->
This paragraph is only for readers.

<!-- narratty: say
Narration only the video has. It may span lines.
-->

<!-- narratty: overlay {text: compose.yaml, style: file} -->

<!-- narratty: hidden
git init demo && cd demo
-->

<!-- narratty: browser {scroll: auto, duration_ms: 6s} -->
The [Compose file reference](https://docs.docker.com/compose/) lists every key.
```

| Comment | Does |
|---|---|
| `skip` | Leaves the next paragraph or block out of the video |
| `say` | Adds narration where it stands; `skip` plus `say` replaces a paragraph |
| `overlay` | Shows an [overlay](spec.md#overlays) in the next scene; takes the same value as the action |
| `hidden` | Runs setup commands in the recorded shell without showing them |
| `browser` | Opens a link of the next paragraph in a [browser view](spec.md#browser-views), see [Opening links](#opening-links) |

HTML comments cannot contain `--`; put such text into a YAML scene instead.

## Opening links

Links are read as plain text. A `browser` comment opens one of them in a
[browser view](spec.md#browser-views) while its paragraph is spoken:

```markdown
<!-- narratty: browser {scroll: auto, duration_ms: 6s} -->
The [Compose file reference](https://docs.docker.com/compose/) lists every key.
```

- Without `link` it opens the first link of the next paragraph; `link: 2` opens the
  second, `link: "Compose file reference"` the one with that text. A URL instead of
  the mapping, `<!-- narratty: browser https://example.com -->`, opens that page.
- The other keys are those of the [browser action](spec.md#browser-views): `scroll`,
  `duration_ms` and `load_ms`.
- The paragraph starts a new scene, so the page appears with it. Like an image, the
  page stays until the next command or heading at the latest.
- A relative link to another page of the docs (`../user-guide/spec.md#overlays`)
  opens the published page: `site_url` from `mkdocs.yml` plus the page's path.
- Web pages need network access: in the container that is
  `sandbox: {network: full}` or an allowlist.

## Code block attributes

An id and per-block options go into one attribute list after the language. mkdocs
uses the id as a link anchor and ignores `narratty`; GitHub ignores both.

````markdown
```console {#install narratty="no-run"}
$ uv tool install narratty
```

```yaml {#spec title="demo.narratty.yaml"}
scenes: []
```
````

`narratty="…"` takes space-separated options:

| Option | Does |
|---|---|
| `no-run` | Types the command, then cancels it with Ctrl+C |
| `hidden` | Runs the block without showing it (setup) |
| `expect-failure` | The block's commands are expected to fail |

!!! warning "Write attributes in braces"
    mkdocs renders `console narratty="no-run"` (without braces) as plain text. A
    brace-less `title="…"` works on its own, but not together with an id.

## Placeholders

Write placeholders as environment variables, which readers can set and copy:

```markdown
$ narratty build "$SPEC" --var target="$TARGET"
```

The video types `$SPEC` as written, so values, including secrets, never appear on
screen. The value comes from [`sandbox.env`](spec.md#sandbox), from
`sandbox.env_passthrough` (you set it on the host) or from a `hidden` comment with an
`export`. A command to run that still contains a placeholder like `<url>` is an
error with the hint to write it as `$URL`.

## The `markdown` entry

The YAML spec stays the entry point. It decides everything at section level and
above: which docs, which sections and in what order, the narration rule and the
overlays. Several videos from one doc are several YAML files.

```yaml
narration: all                      # default for every markdown entry
scenes:
  - markdown: docs/environments.md
    sections: [images, compose]     # nested headings included; unset = whole doc
    heading_overlays: 3
  - id: outro
    narration: That's all you need to get started.
  - markdown: docs/building.md
    narration: none                 # only `say` comments are spoken
    heading_overlays: {levels: 3, breadcrumb: true}
    defaults: {typing_speed_ms: 40}
    overrides:
      install:                      # the block {#install}
        narration: Install it with uv.
        fast: true
        before: [{overlay: "pipx works too"}]
```

| Key | Default | Meaning |
|---|---|---|
| `markdown` | required | The doc, relative to the spec |
| `sections` | whole doc | Headings by TOC slug or title; a list path such as `[compose, services]` picks one of several equal headings |
| `narration` | spec's `narration` (`all`) | `all` speaks every paragraph, `none` only `say` comments |
| `tabs` | `[]` | Preferred content tab labels; otherwise each tab set's first tab |
| `heading_overlays` | none | Show headings down to this level, see [Heading overlays](#heading-overlays) |
| `file_titles` | `true` | Show a file block's title as an overlay |
| `images` | `true` | Show images on a line of their own, see [Images](#images) |
| `id_prefix` | file stem | Start of the generated scene ids |
| `defaults` | `{}` | Scene keys for every scene: `typing_speed_ms`, `pause_ms`, `fast`, `timelapse`, `narration_start`, `expect_exit` |
| `overrides` | `{}` | Per block id: the same scene keys plus `narration` and `before` / `after` action lists |

A missing section or an override for an id that is not in the doc is an error with
a "did you mean". Transitions between docs are ordinary scenes, for example a hidden
`run: cd other && clear` and a scene with an overlay.

## Heading overlays

`heading_overlays: N` shows the headings down to level `N`, each level in its own
built-in style: `heading-1` is a title card in the centre, deeper levels appear at the
top right and fade after a few seconds. `{levels: N, breadcrumb: true}` shows levels 2
to `N` as one overlay instead, `Environments › Compose › Services`, which stays while
its section plays. Long breadcrumbs shorten their middle parts to `…` first
(`max_length`, default 50); `separator` changes the ` › `.

| Style | `position` | `size` | `bold` | `duration_ms` |
|---|---|---|---|---|
| `heading-1` | `center` | `large` | yes | `2.5s` |
| `heading-2` | `top-right` | `large` | yes | `3s` |
| `heading-3` | `top-right` | `medium` | no | `3s` |
| `heading-4` and deeper | `top-right` | `small` | no | `2.5s` |
| `breadcrumb` | `top-right` | `small` | no | until the section ends |
| `file` | `top` | `small` | no | until the scene ends |

Change them like any style in [`overlay_styles`](spec.md#overlays).

## Snippets and mkdocs

The doc is read the way this repo's mkdocs config renders it: admonitions,
collapsible blocks and content tabs (`pymdownx.tabbed`) as above, and
`--8<-- "path"` snippets (with an optional `:start:end` line range) inserted before
reading, relative to the snippets `base_path` in the nearest `mkdocs.yml`, else the
repository root. Errors in an inserted snippet name the snippet file and line.
Headings with an id (`## Title {#custom}`) are selected by that id.

Block snippets (`--8<--` on a line of its own), URL snippets and named snippet
sections are not supported and are reported as errors.

## Checking the result

`narratty validate` reports problems at the Markdown file and line.
`narratty plan --sources SPEC` lists every scene with the Markdown line it comes from,
and what was left out and why. `narratty compile SPEC` prints the spec with every
`markdown` entry replaced by its scenes: a way out of Markdown input, or a frozen copy
to build from.

Sandboxed runs only mount the spec file into the container, so they get the expanded
spec; the Markdown docs stay on the host.

## Not supported yet

- Checking command output against the doc: exit codes are checked, output is not.
- Narration rules beyond `all` and `none`, and a "skip the rest" comment.
- Configurable handling of admonitions per type.
