"""Fase F (etapa 4b, new): score candidate clusters by how likely they are
to be the "relevant" repeated content vs. boilerplate/navigation noise.

This is the highest-risk, most heuristic component in the project (see
plan risks) -- raw repetition count is not a relevance signal (a page's
nav menu routinely repeats more than its actual content table: 146 vs 33
in bancodobrasil.html, 497 vs 12 in dadosabertrosfiocruz.html). Each
signal below is independently testable and documented with the concrete
example that justifies it, so the composite score's weights can be
retuned without having to re-derive the rationale.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from ..content.signature import classify
from ..dom_utils import direct_children_text, full_text
from ..sanitize.boilerplate import NAV_KEYWORD_RE
from .siblings import Cluster

GENERIC_SIGNATURE_TYPES = {"EMPTY", "TEXT", "URL"}

CONTENT_KEYWORD_RE_SOURCE = (
    "result", "row", "record", "item", "card", "resource", "recurso",
    "dataset", "lancamento", "transacao", "table", "views-row",
)
import re as _re
CONTENT_KEYWORD_RE = _re.compile("|".join(_re.escape(k) for k in CONTENT_KEYWORD_RE_SOURCE), _re.IGNORECASE)

# Clusters found via document-wide fingerprint scanning can be very large
# (e.g. 1490 near-identical filter-dropdown options); scoring is O(subtree
# size) per element, so a bounded sample is enough to characterize the
# cluster's shape without scoring all of it.
MAX_ELEMENTS_SAMPLED = 20


# How deep below a candidate element these signals look. Bounded on
# purpose: an UNbounded recursive scan makes a coarse outer wrapper (e.g.
# bancodobrasil.html's legacy nested-table layout, where a `<tr>` at the
# page's outer "resumo" level structurally CONTAINS the entire 122-row
# transaction table many levels down) accumulate all the richness of
# everything nested inside it, so it would always outscore the actual
# leaf-level record it wraps. A record's own informativeness should come
# from its own few levels of fields, not from arbitrarily deep content
# that happens to sit underneath it in the DOM.
SIGNAL_MAX_DEPTH = 3


def _descendants_bounded(el: etree._Element, max_depth: int = SIGNAL_MAX_DEPTH):
    stack = [(child, 1) for child in el if isinstance(child.tag, str)]
    while stack:
        node, depth = stack.pop()
        yield node
        if depth < max_depth:
            stack.extend((child, depth + 1) for child in node if isinstance(child.tag, str))


def _text_length(el: etree._Element) -> int:
    """The record's OWN text, not text pulled from arbitrarily deep nested
    content (same rationale as SIGNAL_MAX_DEPTH above) -- direct children's
    text if it has element children, else its own leaf text."""
    children_text = direct_children_text(el)
    if children_text:
        return sum(len(t) for t in children_text)
    return len(full_text(el))


def _recursive_informative_types(el: etree._Element) -> set[str]:
    types = set()
    for descendant in _descendants_bounded(el):
        text = descendant.text
        if text and text.strip():
            sig_type = classify(text).type
            if sig_type not in GENERIC_SIGNATURE_TYPES:
                types.add(sig_type)
    return types


def _distinct_semantic_descendant_count(el: etree._Element) -> int:
    """Number of distinct (tag, class-or-testid-or-role) descendant shapes
    -- a proxy for "how many separate sub-fields does this record have".
    A bare nav <li><a>Home</a></li> has ~0; a search-result card with a
    title, description, tag list, and metadata badges has several."""
    shapes = set()
    for descendant in _descendants_bounded(el):
        identity = descendant.get("data-testid") or descendant.get("role") or descendant.get("class")
        if identity:
            shapes.add((descendant.tag, identity))
    return len(shapes)


def _keyword_bonus_penalty(el: etree._Element) -> float:
    """Walk up to 4 ancestor levels (plus the element itself) looking for
    content-ish vs. nav-ish keywords in id/class. Bounded walk: going all
    the way to the document root would eventually hit generic wrappers
    that say nothing either way."""
    score = 0.0
    node = el
    for _ in range(5):
        if node is None:
            break
        haystack = f"{node.get('id', '')} {node.get('class', '')}"
        if CONTENT_KEYWORD_RE.search(haystack):
            score += 1.0
        if NAV_KEYWORD_RE.search(haystack):
            score -= 1.0
        node = node.getparent()
    return score


@dataclass(frozen=True)
class ClusterScore:
    cluster: Cluster
    score: float
    signals: dict


def score_cluster(cluster: Cluster) -> ClusterScore:
    sample = cluster.elements[:MAX_ELEMENTS_SAMPLED]
    n = len(sample)

    avg_text_len = sum(_text_length(el) for el in sample) / n
    avg_informative_types = sum(len(_recursive_informative_types(el)) for el in sample) / n
    avg_distinct_fields = sum(_distinct_semantic_descendant_count(el) for el in sample) / n
    avg_keyword = sum(_keyword_bonus_penalty(el) for el in sample) / n

    # log-dampened text length: distinguishes a bare menu label (~10-20
    # chars) from a real record (~50+ chars) without letting one huge
    # blob of prose dominate the score.
    import math

    text_len_signal = math.log1p(avg_text_len)

    signals = {
        "avg_text_len": avg_text_len,
        "avg_informative_types": avg_informative_types,
        "avg_distinct_fields": avg_distinct_fields,
        "avg_keyword": avg_keyword,
    }

    score = (
        1.0 * text_len_signal
        + 3.0 * avg_informative_types
        + 1.5 * avg_distinct_fields
        + 2.0 * avg_keyword
    )
    return ClusterScore(cluster=cluster, score=score, signals=signals)


def rank_clusters(clusters: list[Cluster]) -> list[ClusterScore]:
    scored = [score_cluster(c) for c in clusters if c.count > 0]
    return sorted(scored, key=lambda cs: cs.score, reverse=True)


RICH_SIGNATURE_MIN_FIELDS = 2


def is_rich_signature(content_signature: tuple[str, ...]) -> bool:
    """A signature is "rich" -- informative enough on its own that a
    descendant/covered cluster would be redundant with it -- when it has
    at least 2 fields and at least one of them is a specific type rather
    than generic TEXT/EMPTY/URL. Shared by `select_top_level_clusters`
    (descendant suppression) and `cluster.families` (container detection),
    which both need the same "is this cluster substantive enough to stand
    in for what's nested inside/under it" test."""
    return len(content_signature) >= RICH_SIGNATURE_MIN_FIELDS and any(
        t not in GENERIC_SIGNATURE_TYPES for t in content_signature
    )


def select_top_level_clusters(ranked: list[ClusterScore], max_clusters: int = 10) -> list[ClusterScore]:
    """Greedily take the highest-ranked clusters, skipping any whose
    elements are descendants of an already-selected cluster's elements.

    Document-wide fingerprint scanning finds clusters at every nesting
    level at once (e.g. both a `div.lancamentos` container AND the
    individual `<tr>` rows inside it can each form their own repeated
    cluster). Naively always preferring the outer one is wrong, though:
    on bancodobrasil.html, `div.lancamentos` (count=2) only exposes a
    single TEXT blob as its content signature, while the `<tr>` rows
    inside it (count=122) expose the real DATE|TEXT|CURRENCY|MONEY
    breakdown -- suppressing the rows because the container "already
    covers" them would throw away exactly the information the LLM needs.

    So an outer cluster only blocks its descendants once it is *itself*
    informative enough (>=2 fields, AND at least one of them a specific
    type rather than generic TEXT/EMPTY) that a descendant is actually
    redundant with it. Field *count* alone isn't a safe test: on
    acervodadostecnicosgovbr.html, the page's 2 accordion panels
    ("Organização" / "Recursos", each one giant nested section reduced by
    direct_children_text to 2 TEXT blobs) would otherwise "cover" and
    suppress the real 27-row FILE_FORMAT|TEXT resource cluster nested
    inside the "Recursos" panel -- same failure shape as
    bancodobrasil.html's legacy-nested-table case, just one level up in
    the DOM instead of down.
    """
    selected: list[ClusterScore] = []
    covered: set = set()
    for cs in ranked:
        elements = cs.cluster.elements
        if any(has_covered_ancestor(el, covered) for el in elements):
            continue
        selected.append(cs)
        if is_rich_signature(cs.cluster.content_signature):
            covered.update(elements)
        if len(selected) >= max_clusters:
            break
    return selected


def has_covered_ancestor(el, covered: set) -> bool:
    """True if some ancestor of `el` is in `covered`. Shared by
    `select_top_level_clusters` (descendant suppression) and
    `cluster.families` (container-of-a-repeater detection), which both need
    to test "is this element nested inside one of these other elements"."""
    node = el.getparent()
    while node is not None:
        if node in covered:
            return True
        node = node.getparent()
    return False


# Backwards-compatible alias for the original private name.
_has_covered_ancestor = has_covered_ancestor
