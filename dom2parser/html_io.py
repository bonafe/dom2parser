"""Loading and parsing of source HTML documents."""

from __future__ import annotations

from pathlib import Path

from lxml import etree, html


def parse_html(source: str | bytes) -> etree._Element:
    """Parse an HTML document (string, bytes, or path-like content) into an lxml tree.

    Uses lxml's recovering HTML parser, which tolerates the malformed markup
    commonly found in real-world pages (unclosed tags, invalid nesting, etc.).
    """
    parser = html.HTMLParser(recover=True, encoding="utf-8" if isinstance(source, str) else None)
    if isinstance(source, str):
        source = source.encode("utf-8")
    root = etree.fromstring(source, parser=parser)
    if root is None:
        raise ValueError("Failed to parse HTML: no root element produced")
    return root


def load_html_file(path: str | Path) -> etree._Element:
    """Read and parse an HTML file from disk."""
    data = Path(path).read_bytes()
    return parse_html(data)


def describe(root: etree._Element) -> dict:
    """Cheap structural summary used for smoke-testing that a document loaded sanely."""
    tag_count = sum(1 for _ in root.iter(etree.Element))
    text_len = sum(len(t) for t in root.itertext())
    return {
        "tag_count": tag_count,
        "text_len": text_len,
    }
