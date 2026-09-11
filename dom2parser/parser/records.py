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

from collections import Counter

from lxml import etree

from ..compact.paths import location_key
from ..fingerprint.hashattrs import semantic_class_tokens
from ..fingerprint.structural import compute_fingerprint, fingerprint_key

MAX_PROMOTION_LEVELS = 6
MAX_SPAN = 4


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


def _identity_signals(el) -> int:
    return (
        int(bool(el.get("data-testid")))
        + int(bool(semantic_class_tokens(el.get("class", ""))))
        + int(bool(el.get("id")))
    )


def _sibling_positions(anchors: list) -> tuple[list, list[int]] | None:
    """The anchors' shared parent's element children and the anchors'
    positions among them, or None when the anchors have several parents."""
    if len(anchors) < 2:
        return None
    parent = anchors[0].getparent()
    if parent is None or any(a.getparent() is not parent for a in anchors):
        return None
    kids = [c for c in parent if isinstance(c.tag, str)]
    index = {id(c): i for i, c in enumerate(kids)}
    return kids, sorted(index[id(a)] for a in anchors)


def period(anchors: list) -> int:
    """How many consecutive siblings make one record when `anchors` are the
    records' first elements; 1 when each anchor is a whole record.

    Some pages spread one record over several siblings under a shared
    parent: a Hacker News item is `tr.athing` + a subtext `tr` + a spacer;
    a glossary entry is `dt` + `dd`. Cut the parent's children at each
    anchor and the segments repeat a pattern -- `(tr, tr, tr)`, `(dt, dd)`.
    The modal segment length is the span. A segment may end early (two
    terms sharing one definition) but never run long; the last one is the
    exception, since it runs to the parent's end and a trailing footer row
    (Hacker News's "More" link) lands in it -- only its head has to fit."""
    located = _sibling_positions(anchors)
    if located is None:
        return 1
    kids, positions = located
    return _regular_span(kids, positions) or 1


def anchor_offsets(anchors: list) -> list[int]:
    """Candidate shifts from the elements given to the record's natural
    anchor, most identity first.

    The family may have landed on the wrong member of the pattern -- the
    `dd` rather than the `dt` -- and pairing each definition with the NEXT
    term would be silently wrong. The natural anchor is the position in
    the pattern carrying the most identity (testid, class, id). Whether a
    shift is right cannot be judged here: seen from the `dd` the entry
    where two terms share a definition is irregular, and the orphan `dt`
    only joins the set once the caller re-closes the shifted anchors. So
    this ranks; the caller shifts, re-closes, re-verifies, and asks
    `period` again."""
    located = _sibling_positions(anchors)
    if located is None:
        return [0]
    kids, positions = located
    scored = []
    for offset in range(MAX_SPAN):
        if positions[0] - offset < 0:
            break
        shifted = [kids[p - offset] for p in positions]
        if len({el.tag for el in shifted}) != 1:
            continue
        scored.append((-sum(_identity_signals(el) for el in shifted), offset))
    scored.sort()
    return [offset for _, offset in scored] or [0]


def _regular_span(kids: list, positions: list[int]) -> int:
    """The pattern length when the segments cut at `positions` repeat one
    pattern (every inner segment a prefix of the modal one, the last
    segment's head matching it), else 0."""
    bounds = positions[1:] + [len(kids)]
    segments = [tuple(c.tag for c in kids[start:end]) for start, end in zip(positions, bounds)]
    inner, last = segments[:-1], segments[-1]
    if not inner:
        return 0
    modal, share = Counter(inner).most_common(1)[0]
    span = len(modal)
    if span < 2 or share * 2 <= len(inner):
        return 0
    if any(len(s) > span or s != modal[: len(s)] for s in inner):
        return 0
    head = last[:span]
    if head != modal[: len(head)]:
        return 0
    return span


def shift_anchors(anchors: list, offset: int) -> list:
    """Each anchor's `offset`-th preceding element sibling."""
    out = []
    for anchor in anchors:
        node = anchor
        for _ in range(offset):
            node = node.getprevious()
            while node is not None and not isinstance(node.tag, str):
                node = node.getprevious()
        if node is not None:
            out.append(node)
    return out


__all__ = [
    "anchor_offsets",
    "closure",
    "closure_of",
    "period",
    "promote",
    "shift_anchors",
    "structural_identity",
]
