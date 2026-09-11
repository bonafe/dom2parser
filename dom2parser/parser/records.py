"""Fase J: find the element a human would call "the record".

A `Family` is not it, for two independent reasons measured on the corpus.

**It is incomplete.** Clustering buckets by content signature and then
drops buckets below `min_cluster_size`, so a row that happens to classify
differently gets stranded. On bancodobrasil.html the family holds 152 rows
while `div.lancamentos table tr` holds 154; the two missing ones are
ordinary transactions whose description starts with a digit
(`"1 - FERNANDO FERNANDES"`), which makes them `COUNT_LABELED`, which
makes them singletons, which drops them. They are data, not noise.
`closure()` puts them back by asking a purely structural question.

**It is too deep.** `content_signature_sequence` reads the text of an
element's *direct children*, so ranking systematically prefers the
deepest level at which children still classify into distinct types --
which is an inner wrapper, not the record. Measured overlap between the
family's elements and the hand-written ground-truth record elements is
**zero** on folhadesp.html, dadosabertrosfiocruz.html,
conjuntodadosgovbr.html and oss_gov_br_whatsapp.html; in each case the
family sits strictly inside the real record. Extracting from the family
would yield fragments of a record, never a record.

`promote()` climbs out of the wrapper. The stopping rule is that parents
stay **injective**: while every element has its own distinct parent, the
level above is still one-node-per-record and is a better record boundary.
The moment several elements share a parent, that parent is the *container*
of the whole collection, not a record, so the climb stops. Measured, this
lands exactly on the ground-truth record set for dadosabertrosfiocruz.html
(`div.views-row`, 12) and conjuntodadosgovbr.html
(`div.search-result.container`, 10), and on the correct `li` level for
folhadesp.html.
"""

from __future__ import annotations

from lxml import etree

from ..compact.paths import location_key
from ..fingerprint.structural import compute_fingerprint, fingerprint_key

MAX_PROMOTION_LEVELS = 6


def structural_identity(el, cache: dict | None = None) -> tuple:
    """The `(structural_key, location_key)` pair `cluster.families` groups
    by, computed for any element rather than for a whole cluster.

    Mirrors `families._family_key`'s normalisation: when identity fell all
    the way back to bare shape, the exact children-tag tuple is dropped so
    a row with one optional extra child still counts as the same kind."""
    structural = fingerprint_key(compute_fingerprint(el))
    if len(structural) > 2 and structural[1] == ("shape",):
        structural = structural[:2]
    return (structural, location_key(el, cache=cache))


def closure(family, clean_root, cache: dict | None = None) -> list:
    """Every element of `clean_root` structurally equivalent to the
    family's members, regardless of content signature or cluster size."""
    members = [el for m in family.members for el in m.cluster.elements]
    if not members:
        return []
    wanted = {structural_identity(el, cache) for el in members}
    return [el for el in clean_root.iter(etree.Element) if structural_identity(el, cache) in wanted]


def promote(elements: list) -> list[list]:
    """Successive record-boundary candidates, innermost first.

    Climbing stops as soon as two elements share a parent: that parent
    holds the collection, so the level below it is the record."""
    levels = [elements]
    current = elements
    for _ in range(MAX_PROMOTION_LEVELS):
        parents = [el.getparent() for el in current]
        if any(parent is None for parent in parents):
            break
        if len({id(parent) for parent in parents}) != len(current):
            break
        current = parents
        levels.append(current)
    return levels


__all__ = ["closure", "promote", "structural_identity"]
