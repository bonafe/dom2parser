"""Fase E: group candidate elements into clusters of "the same kind of
record", tolerating optional fields.

Two-level grouping, because DOM structure alone is not enough -- this is
the spec's own conclusion from the Banco do Brasil case study: a
transaction row, a category-header row, and an empty spacer row can all be
`tr(td, td, td, td)` with no distinguishing class, yet are clearly
different *kinds* of record. So:

1. Group by DOM fingerprint (Etapa 2 / Fase C) -- structural equivalence.
   Optional child fields (the CKAN case: a "quality badge" present in only
   6 of 10 otherwise-identical cards) do NOT fragment this level, because
   fingerprint_key ignores children_tags whenever an element has a
   testid/role/class/id identity (see structural.py) -- exactly the case
   for card-shaped containers.

2. Within each structural group, sub-group by the *content signature
   sequence* of direct children's text (Etapa 3 / Fase D) -- this is what
   separates BB's transaction/section/empty/special rows, which share one
   DOM fingerprint but have different DATE|TEXT|CURRENCY|MONEY-shaped
   content.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from lxml import etree

from ..content.signature import classify
from ..dom_utils import direct_children_text
from ..fingerprint.structural import compute_fingerprint, fingerprint_key


@dataclass
class Cluster:
    structural_key: tuple
    content_signature: tuple[str, ...]
    elements: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.elements)


def group_by_fingerprint(
    elements: list[etree._Element],
    build_artifact_attrs: frozenset[str] = frozenset(),
) -> dict[tuple, list[etree._Element]]:
    groups: dict[tuple, list[etree._Element]] = defaultdict(list)
    for el in elements:
        key = fingerprint_key(compute_fingerprint(el, build_artifact_attrs))
        groups[key].append(el)
    return groups


def content_signature_sequence(el: etree._Element) -> tuple[str, ...]:
    """The content-signature type of each direct child's text -- e.g. a
    <tr>'s <td> children classify as (DATE, TEXT, CURRENCY, MONEY)."""
    return tuple(classify(text).type for text in direct_children_text(el))


def cluster_siblings(
    elements: list[etree._Element],
    build_artifact_attrs: frozenset[str] = frozenset(),
) -> list[Cluster]:
    clusters: list[Cluster] = []
    for structural_key, group_elements in group_by_fingerprint(elements, build_artifact_attrs).items():
        by_content: dict[tuple, list] = defaultdict(list)
        for el in group_elements:
            by_content[content_signature_sequence(el)].append(el)
        for content_seq, els in by_content.items():
            clusters.append(Cluster(structural_key=structural_key, content_signature=content_seq, elements=els))
    return clusters


def optional_field_presence(
    cluster: Cluster,
    build_artifact_attrs: frozenset[str] = frozenset(),
) -> Counter:
    """For each semantically-identifiable descendant fingerprint (i.e. one
    that resolved to testid/role/class/id, not bare tag+shape -- unlabeled
    generic wrapper divs are too noisy to treat as a "field"), count in how
    many of the cluster's elements it appears at least once."""
    presence: Counter = Counter()
    for el in cluster.elements:
        seen = set()
        for descendant in el.iter(etree.Element):
            if descendant is el:
                continue
            fp = compute_fingerprint(descendant, build_artifact_attrs)
            if fp.identity[0] == "shape":
                continue
            seen.add(fingerprint_key(fp))
        for key in seen:
            presence[key] += 1
    return presence


def optional_fields(
    cluster: Cluster,
    build_artifact_attrs: frozenset[str] = frozenset(),
) -> dict[tuple, int]:
    """Subset of optional_field_presence present in SOME but not ALL of the
    cluster's elements -- the "quase idênticos com campos opcionais" the
    spec calls out for the CKAN result cards."""
    presence = optional_field_presence(cluster, build_artifact_attrs)
    n = cluster.count
    return {key: count for key, count in presence.items() if 0 < count < n}
