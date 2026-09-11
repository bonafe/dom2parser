"""Fase I: a bridge between the original document and the sanitized copy
the pipeline actually clusters over.

`sanitize.strip.sanitize()` deep-copies before it deletes anything, so a
`Cluster.elements` handle points into a tree that is NOT the document a
generated parser must run against -- and the spec is explicit that the
parser runs on the original full HTML. Worse, the clean tree is not even
structurally parallel: nav/sidebar/hidden subtrees are gone, so "same
position" is not a usable correspondence.

So each element of the original gets stamped with a unique id BEFORE the
copy is taken. The copy inherits the attribute, and any clean element can
then name its original exactly. `attrs.strip_noisy_attrs` is a denylist,
so the stamp survives sanitization; no identity rule in
`fingerprint.structural` looks at it, so clustering is unaffected.

The one stage it does disturb is `sanitize.dedup_subtree`, which hashes
the serialized subtree including every attribute -- a unique stamp per
element makes every subtree unique and silently disables it (measured:
folhadesp.html went from 1520 removed elements to 0). That module excludes
`UID_ATTR` from its hash for this reason; the two files have to stay in
sync.
"""

from __future__ import annotations

from lxml import etree

UID_ATTR = "data-d2p-uid"


def stamp_uids(root: etree._Element) -> etree._Element:
    """Stamp every element with a document-unique id, in place. Must run on
    the original tree before it is sanitized, so the copy inherits it."""
    for i, el in enumerate(root.iter(etree.Element)):
        el.set(UID_ATTR, str(i))
    return root


def build_index(root: etree._Element) -> dict[str, etree._Element]:
    """Map stamp -> element, for resolving clean elements back to original."""
    return {
        uid: el for el in root.iter(etree.Element) if (uid := el.get(UID_ATTR)) is not None
    }


def to_original(clean_el, index: dict[str, etree._Element]):
    """The original-tree element a clean-tree element came from, or None.

    None is expected, not exceptional: `dedup_subtree` replaces collapsed
    subtrees with fresh `<template-ref>` placeholders that never carried a
    stamp."""
    uid = clean_el.get(UID_ATTR)
    return index.get(uid) if uid is not None else None


def originals_for(clean_elements, index: dict[str, etree._Element]) -> list:
    """`to_original` over a list, dropping unmappable elements."""
    out = []
    for el in clean_elements:
        original = to_original(el, index)
        if original is not None:
            out.append(original)
    return out


def strip_uids(root: etree._Element) -> None:
    """Remove every stamp, in place."""
    for el in root.iter(etree.Element):
        el.attrib.pop(UID_ATTR, None)
