"""Links of a doc as a browser opens them: web URLs as written, doc pages on the site.

A relative link to another page (``../user-guide/spec.md#overlays``) is mapped to the
published site the way mkdocs builds it: ``site_url`` plus the page's path under
``docs_dir``, with ``use_directory_urls`` (``spec/`` instead of ``spec.html``).
"""

from __future__ import annotations

import posixpath
from pathlib import Path

from narratty.spec.markdown.source import mkdocs_config


class LinkError(ValueError):
    """A link that cannot be opened in a browser view."""


def resolve_link(href: str, doc: Path) -> str:
    """The URL a browser view opens for ``href``, written in the Markdown file ``doc``."""
    if "://" in href:
        return href
    if href.startswith(("mailto:", "tel:")):
        raise LinkError(f"{href} is not a web page")
    found = mkdocs_config(doc)
    site_url = str(found[1].get("site_url") or "") if found else ""
    if found is None or not site_url:
        raise LinkError(f"{href} is relative; set site_url in mkdocs.yml or link the full URL")
    folder, data = found
    docs_dir = (folder / str(data.get("docs_dir", "docs"))).resolve()
    try:
        page = doc.resolve().relative_to(docs_dir).as_posix()
    except ValueError as error:
        raise LinkError(f"{doc} is not under docs_dir {docs_dir}") from error
    path, _, anchor = href.partition("#")
    target = posixpath.normpath(posixpath.join(posixpath.dirname(page), path)) if path else page
    if target.startswith(".."):
        raise LinkError(f"{href} points outside docs_dir")
    directory_urls = data.get("use_directory_urls", True) is not False
    url = site_url.rstrip("/") + "/" + _page_path(target, directory_urls=directory_urls)
    return url + (f"#{anchor}" if anchor else "")


def _page_path(target: str, *, directory_urls: bool) -> str:
    """``user-guide/spec.md`` as mkdocs publishes it."""
    if not target.endswith(".md"):
        return target
    stem = target.removesuffix(".md")
    if stem == "index" or stem.endswith("/index"):
        return stem.removesuffix("index")
    if stem.endswith("/README") or stem == "README":
        return stem.removesuffix("README")
    return f"{stem}/" if directory_urls else f"{stem}.html"
