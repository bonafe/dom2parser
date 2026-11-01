"""Fase K (context): the title of the group a record belongs to.

Some lists are split into groups by a title that is not inside any record:
bancodobrasil.com.br's new statement puts one heading per day
(`<h3>01 de outubro, quinta</h3>`) above that day's entry lines, and the
date of an entry is nowhere else. Read record by record, the date is lost;
read day by day, every entry after the first is lost (a day becomes one
record with its lines as positional columns). The record is the line, and
the group title is a field of it that lives *before* it.

`group_title` finds that field. For every record, the nearest preceding
text leaf in document order that is outside every record. It is a group
title only when the same kind of element (tag and class) plays that part
for every record, and the records share it -- some title heads more than
one record, and there is more than one title. A title that heads exactly
one record each is the record's neighbour, not its group.

The locator is an XPath on the `preceding` axis, evaluated from the
record's anchor (`FieldEntry.axis == "preceding"`), and it is verified to
reach the same element the search found, for every record.
"""

from __future__ import annotations

from lxml.etree import XPath

from ..fingerprint.hashattrs import semantic_class_tokens
from .fields import SKIP_TAGS, FieldSpec, _column_type, _is_text_leaf, field_text

#: How far back the search looks for a title, in elements.
MAX_LOOKBEHIND = 400


def _inside_any(el, anchors: set) -> bool:
    node = el
    while node is not None:
        if node in anchors:
            return True
        node = node.getparent()
    return False


def _backwards(el):
    """The elements before `el` in document order, nearest first, ancestors
    excluded (the `preceding` axis), without materialising the whole axis."""
    node = el
    while node is not None:
        for sibling in node.itersiblings(preceding=True):
            yield from reversed(list(sibling.iter()))
        node = node.getparent()


def _preceding_title(anchor, anchors: set):
    for n, el in enumerate(_backwards(anchor)):
        if n >= MAX_LOOKBEHIND:
            return None
        if not isinstance(el.tag, str) or el.tag in SKIP_TAGS:
            continue
        if _is_text_leaf(el) and field_text(el) and not _inside_any(el, anchors):
            return el
    return None


def _kind(el) -> tuple:
    return (el.tag, tuple(semantic_class_tokens(el.get("class", ""))))


def _locators(el) -> list[str]:
    out = [
        f"preceding::{el.tag}[contains(concat(' ', normalize-space(@class), ' '), ' {cls} ')][1]"
        for cls in semantic_class_tokens(el.get("class", ""))
    ]
    out.append(f"preceding::{el.tag}[1]")
    return out


def group_title(records: list, taken: set[str]) -> FieldSpec | None:
    """The group-title field of `records` (original-tree anchors), or None."""
    if len(records) < 2:
        return None
    anchors = set(records)
    titles = [_preceding_title(r, anchors) for r in records]
    if any(t is None for t in titles) or len({_kind(t) for t in titles}) != 1:
        return None
    distinct = {id(t) for t in titles}
    if not 1 < len(distinct) < len(records):
        return None
    for locator in _locators(titles[0]):
        xpath = XPath(locator)
        if all((hits := xpath(r)) and hits[0] is t for r, t in zip(records, titles)):
            break
    else:
        return None
    name, n = "group_title", 1
    while name in taken:
        n += 1
        name = f"group_title_{n}"
    values = [field_text(t) for t in titles]
    return FieldSpec(
        name=name,
        name_source="group_title",
        locator=locator,
        type=_column_type(values, None),
        capture="text",
        attribute=None,
        present=len(records),
        total=len(records),
        axis="preceding",
    )


__all__ = ["group_title"]
