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


def structural_identity(el, cache: dict | None = None, reused_ids: frozenset[str] = frozenset()) -> tuple:
    """The `(structural_key, location_key)` pair `cluster.families` groups
    by, computed for any element rather than for a whole cluster.

    Mirrors `families._family_key`'s normalisation: when identity fell all
    the way back to bare shape, the exact children-tag tuple is dropped so
    a row with one optional extra child still counts as the same kind."""
    structural = fingerprint_key(compute_fingerprint(el, reused_ids))
    if len(structural) > 2 and structural[1] == ("shape",):
        structural = structural[:2]
    return (structural, location_key(el, cache=cache))


def closure(family, clean_root, cache: dict | None = None, reused_ids: frozenset[str] = frozenset()) -> list:
    """Every element of `clean_root` structurally equivalent to the
    family's members, regardless of content signature or cluster size."""
    members = [el for m in family.members for el in m.cluster.elements]
    return closure_of(members, clean_root, cache, reused_ids)


def closure_of(members: list, clean_root, cache: dict | None = None, reused_ids: frozenset[str] = frozenset()) -> list:
    """`closure` for an arbitrary set of clean-tree elements -- used again
    after promotion, because climbing out of a wrapper can land on a level
    the seed did not fully cover. docs.python.org's library index: 36
    nested `ul` promote to their 36 `li.toctree-l1`, but the page has 40
    such `li`; four have no nested list. The boundary is right, the set
    is not, and only re-closing at the boundary completes it."""
    if not members:
        return []
    wanted = {structural_identity(el, cache, reused_ids) for el in members}
    # A family identified only by shape (no class/testid of its own) also
    # owns same-tag siblings at the same location that happen to carry a
    # modifier class. Wikipedia's population table: 196 bare `tr` plus 45
    # `tr.static-row-numbers-norank` are one table, and the selector a
    # human writes -- `table.wikitable tr` -- says so. A class-identified
    # family keeps exact matching: `div.quote` and `div.footer` under one
    # parent are different kinds.
    by_place = {
        (structural[0], location)
        for structural, location in wanted
        if structural[1] == ("shape",)
    }
    out = []
    for el in clean_root.iter(etree.Element):
        identity = structural_identity(el, cache, reused_ids)
        if identity in wanted or (identity[0][0], identity[1]) in by_place:
            out.append(el)
    return out


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


__all__ = ["closure", "closure_of", "promote", "structural_identity"]
