"""Fase 1 (basic): drop element types and attribute values that never help
generate a parser -- scripts, styles, decorative SVG, comments, meta/link
tags, and inline data: URIs.

Attribute allow/deny-listing (Fase B) lives in attrs.py; this module only
removes whole subtrees/nodes and oversized inline data that are noise
regardless of any allowlist.
"""

from __future__ import annotations

import copy
import re

from lxml import etree

REMOVED_TAGS = ("script", "style", "svg", "noscript", "meta", "link")

DATA_URI_RE = re.compile(r"^data:[^,]*,", re.IGNORECASE)
DATA_URI_PLACEHOLDER = "data:<inline-omitted>"


def strip_comments(root: etree._Element) -> None:
    for comment in root.xpath("//comment()"):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)


def strip_tags(root: etree._Element, tags: tuple[str, ...] = REMOVED_TAGS) -> None:
    etree.strip_elements(root, *tags, with_tail=True)


def truncate_data_uris(root: etree._Element) -> None:
    """Replace data: URI attribute values (base64 images, inline fonts, ...)
    with a short placeholder -- keeps the attribute (its presence can matter
    structurally) without paying its token cost."""
    for el in root.iter(etree.Element):
        for name, value in list(el.attrib.items()):
            if value and DATA_URI_RE.match(value.strip()):
                el.set(name, DATA_URI_PLACEHOLDER)


def sanitize(root: etree._Element) -> etree._Element:
    """Return a sanitized copy of root. Does not mutate the input tree."""
    clone = copy.deepcopy(root)
    strip_comments(clone)
    strip_tags(clone)
    truncate_data_uris(clone)
    return clone
