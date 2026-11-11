# Constructs

Intro with `inline code`, a [link](https://example.com) and **emphasis**.
It spans two lines.

```console
$ echo hello
hello
$ printf '%s\n' \
> a b
a
b
```

A paragraph after the last block stays on screen.

## Lists {#lists}

- First item
- Second item ends with a colon:

    ```bash
    # comment lines are not typed
    mkdir demo
    cd demo
    ```

1. Ordered item.

## Callouts

> [!NOTE]
> A GitHub alert.

!!! note "Not spoken title"
    The note body is spoken.

??? tip "Collapsed"
    Left out.

    ```bash
    echo left out
    ```

???+ warning
    An open collapsible is spoken.

<details markdown>
<summary>More</summary>

Also left out.

</details>

## Left out

| A | B |
|---|---|
| table | cells |

![An image](image.png)

<video src="demo.mp4"></video>

<!-- narratty: say
Kept for step 4.
-->

```yaml
key: untitled files are skipped
```

```console {#install narratty="no-run" title="Install"}
$ uv tool install narratty
```

## Callouts

The second "Callouts" heading gets the slug callouts_1.
