"""Fase C: a per-element structural fingerprint used to decide whether two
elements are "the same kind of thing" -- ignoring text content, per the
spec's Etapa 2.

Identity signal fallback chain (highest to lowest priority):

    data-testid -> role/aria-* -> semantic class tokens -> id -> tag+children-shape

data-testid and role are checked first because, empirically, when present
they are *type* markers reused identically across every instance of a
component (e.g. `data-testid="cell-frame-container"` on all 23 WhatsApp
chat rows) -- exactly what's needed to group siblings.

`id` counts as identity ONLY when the document reuses it on more than
one element. By HTML convention an id is unique per element, so a unique
id says nothing about what *kind* of element this is -- and treating it
as identity makes every instance fingerprint as unique and defeats
clustering. The reused case is the (invalid but real) one where a page
uses an id as a de facto class (`#btnDownloadUrl` x28 in
acervodadostecnicosgovbr.html), and that is the only case worth keeping.

The rule matters most on generated markup. MediaWiki's Parsoid stamps a
unique `id="mwBlw"`-style token on 75% of all elements in a Wikipedia
article; with unique ids as identity, a 242-row table shattered into
clusters of 5, 22 and 16 rows and never produced a record selector.
`reused_ids()` computes the set once per document; callers thread it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from lxml import etree

from .hashattrs import semantic_class_tokens


@dataclass(frozen=True)
class Fingerprint:
    tag: str
    identity: tuple
    children_tags: tuple[str, ...]

    @property
    def n_children(self) -> int:
        return len(self.children_tags)


def _aria_signal(el: etree._Element) -> str | None:
    for name, value in el.attrib.items():
        if name.lower().startswith("aria-") and value:
            return f"{name}={value}"
    return None


def reused_ids(root: etree._Element) -> frozenset[str]:
    """The id values carried by more than one element of `root` -- the only
    ids that can act as identity, since a unique id groups nothing."""
    counts = Counter(el.get("id") for el in root.iter(etree.Element) if el.get("id"))
    return frozenset(value for value, n in counts.items() if n >= 2)


def compute_fingerprint(
    el: etree._Element,
    reused_ids: frozenset[str] = frozenset(),
) -> Fingerprint:
    tag = el.tag if isinstance(el.tag, str) else "?"

    testid = el.get("data-testid")
    role = el.get("role")
    classes = semantic_class_tokens(el.get("class", ""))
    aria = _aria_signal(el)
    el_id = el.get("id")

    if testid:
        identity = ("testid", testid)
    elif role:
        identity = ("role", role)
    elif classes:
        identity = ("class", classes)
    elif aria:
        identity = ("aria", aria)
    elif el_id and el_id in reused_ids:
        identity = ("id", el_id)
    else:
        identity = ("shape",)

    children_tags = tuple(
        child.tag for child in el if isinstance(child.tag, str)
    )
    return Fingerprint(tag=tag, identity=identity, children_tags=children_tags)


def is_meaningful_candidate(fp: Fingerprint) -> bool:
    """False for elements too structurally trivial to cluster meaningfully
    when they have no semantic identity (testid/role/class/id) to fall
    back on -- e.g. a bare `<table><tbody>...</tbody></table>` wrapper has
    identity=("shape",) and children_tags=("tbody",) REGARDLESS of what's
    inside the tbody, so every unrelated table on a page would otherwise
    fingerprint identically and falsely merge into one cluster (confirmed
    on bancodobrasil.html: 7 unrelated tables, one fingerprint). Requiring
    at least 2 children for a bare-shape identity means the real repeated
    pattern is left to be found one level down, where children_tags
    actually carries information (e.g. tbody's children_tags is the full
    tr-tag sequence, which differs between unrelated tables)."""
    if fp.identity != ("shape",):
        return True
    return len(fp.children_tags) >= 2


def filter_meaningful_candidates(
    elements,
    reused_ids: frozenset[str] = frozenset(),
):
    return [el for el in elements if is_meaningful_candidate(compute_fingerprint(el, reused_ids))]


def fingerprint_key(fp: Fingerprint) -> tuple:
    """A hashable grouping key -- two elements with the same key are
    considered structurally equivalent candidates for the same cluster
    (Fase E). Ignores children_tags on purpose when identity is already
    specific (testid/role/class), since content-bearing siblings of the
    "same kind" can still legitimately vary in child count (Fase E's
    tolerance for optional fields) -- but requires structural agreement
    when identity fell all the way back to bare shape."""
    if fp.identity == ("shape",):
        return (fp.tag, fp.identity, fp.children_tags)
    return (fp.tag, fp.identity)
