"""Fase L: assemble a `ParserSpec` from the ranked families.

Promotion offers several candidate record boundaries (see
`parser.records`); this picks the OUTERMOST one that still yields an exact
selector. Outermost, because the inner levels are wrappers -- measured
against the hand-written ground truth, that rule lands on `div.views-row`
rather than the `span` inside it, on `div.search-result.container` rather
than the `div.row` inside it, and on `li.c-headline` rather than the
`div.c-headline__wrapper` inside it. Exact, because a boundary whose
selector also catches unrelated elements is not a boundary.

A family that produces no exact selector at any level is recorded under
`failures`, with the near-misses that came closest. It is never emitted as
a record: a selector that half works produces a parser that half works,
and the caller cannot tell.
"""

from __future__ import annotations

from lxml import etree

from ..anchor import UID_ATTR, build_index, originals_for, stamp_uids
from ..cluster.families import build_families
from ..cluster.rank import rank_clusters, select_top_level_clusters
from ..cluster.siblings import cluster_siblings
from ..fingerprint.hashattrs import semantic_class_tokens
from ..fingerprint.structural import filter_meaningful_candidates, reused_ids
from ..html_io import parse_html
from ..sanitize import full_sanitize
from .fields import capture_value, discover, is_decoration, relative_locator, scoped_element
from .naming import slugify
from .records import anchor_offsets, closure, closure_of, period, promote, shift_anchors
from .selector import synthesize
from .spec import SCHEMA_VERSION, FieldEntry, ParserSpec, RecordEntry


MAX_REPORTED_MISSES = 5


def _record_name(selector: str, taken: set[str]) -> str:
    tail = selector.replace(">", " ").split()[-1]
    base = slugify(tail.split(".")[-1].split("[")[0] or "record") or "record"
    name, n = base, 1
    while name in taken:
        n += 1
        name = f"{base}_{n}"
    taken.add(name)
    return name


def _has_identity(el) -> bool:
    return bool(el.get("data-testid")) or bool(semantic_class_tokens(el.get("class", "")))


def _best_level(family, clean, root, index, clean_index, cache, document_ids):
    """The record boundary: among promotion levels with an exact selector,
    the outermost one whose elements carry identity of their own, else the
    outermost of all.

    Identity breaks the tie between 1:1 wrappers. books.toscrape.com nests
    `article.product_pod` inside a bare `li`; both select the same twenty
    records, but a human names the article, and so does the ground truth.
    Each level is re-closed before synthesis (see `records.closure_of`)."""
    seed = closure(family, clean, cache, document_ids)
    if not seed:
        return None, None, (), 1

    exact, inexact = [], []
    for level in promote(originals_for(seed, index)):
        in_clean = [clean_index[uid] for el in level if (uid := el.get(UID_ATTR)) in clean_index]
        completed = originals_for(closure_of(in_clean, clean, cache, document_ids), index) or level
        result = synthesize(completed, root)
        if not result.ok:
            inexact.extend(result.near_misses)
        elif result.fit.precision == 1.0:
            exact.append((completed, result.fit))
        else:
            inexact.append(result.fit)
    if not exact:
        inexact.sort(key=lambda f: (-f.recall, -f.precision, len(f.selector)))
        return None, None, tuple(inexact[:MAX_REPORTED_MISSES]), 1
    # A level made of decorations -- the `¶` permalinks hanging off every
    # glossary term -- is never the record, however exact its selector and
    # however confidently `a.headerlink` names itself.
    usable = [pair for pair in exact if not is_decoration(pair[0][0])] or exact
    identified = [pair for pair in usable if _has_identity(pair[0][0])]
    elements, fit = (identified or usable)[-1]

    # The record may be several siblings wide, and the family may sit on
    # the wrong one (see records.anchor_offsets). A shift changes the
    # element set, so it is re-closed and re-verified before `period` is
    # asked whether the result is regular; the first offset that passes
    # wins, and none passing leaves the record one sibling wide.
    for offset in anchor_offsets(elements):
        if offset == 0:
            span = period(elements)
            if span > 1:
                return elements, fit, (), span
            continue
        shifted = shift_anchors(elements, offset)
        in_clean = [clean_index[uid] for el in shifted if (uid := el.get(UID_ATTR)) in clean_index]
        completed = originals_for(closure_of(in_clean, clean, cache, document_ids), index) or shifted
        result = synthesize(completed, root)
        if result.ok and result.fit.precision == 1.0 and period(completed) > 1:
            return completed, result.fit, (), period(completed)
    return elements, fit, (), 1


def specs_for_families(families, clean, root, index) -> tuple[ParserSpec, dict[int, RecordEntry]]:
    """Synthesize a parser for already-built families.

    Returns the spec and a map from each family's position to the record it
    produced, so a caller holding the same families (the compact renderers)
    can show the selector and field names alongside the structure they
    describe instead of re-deriving them."""
    cache: dict = {}
    records, failures, taken = [], [], set()
    by_family: dict[int, RecordEntry] = {}
    emitted: set[frozenset] = set()
    document_ids = reused_ids(clean)
    clean_index = build_index(clean)
    for position, family in enumerate(families):
        elements, fit, near_misses, span = _best_level(
            family, clean, root, index, clean_index, cache, document_ids
        )
        if fit is None:
            failures.append(
                {
                    "reason": "no_exact_selector",
                    "near_misses": [
                        {
                            "selector": m.selector,
                            "matched": m.matched,
                            "expected": m.expected,
                            "precision": round(m.precision, 4),
                            "recall": round(m.recall, 4),
                        }
                        for m in near_misses
                    ],
                }
            )
            continue

        # Several families (a card, the title inside it, the price inside
        # it) routinely promote to the same record boundary. That is one
        # record, not three -- measured as triplicate entries on three of
        # seven public corpus pages.
        record_set = frozenset(el.get(UID_ATTR) for el in elements)
        if record_set in emitted:
            continue
        emitted.add(record_set)

        found = discover(elements, span)
        header_values = _header_values(elements, found)
        # A record whose every field is empty carries no information; it
        # is a spacer row, or a header row whose cells are `th` where the
        # locators expect `td`. Skipped, never dropped -- the executor
        # reports it with its reason.
        skip_when = {"all_empty": True}
        if header_values:
            skip_when["header_values"] = header_values

        entry = RecordEntry(
            name=_record_name(fit.selector, taken),
            selector=fit.selector,
            count=len(elements),
            fields=[
                FieldEntry(
                    name=f.name,
                    locator=f.locator,
                    type=f.type,
                    capture=f.capture,
                    attribute=f.attribute,
                    required=f.required,
                    present=f.present,
                    total=f.total,
                    name_source=f.name_source,
                    sibling=f.sibling,
                )
                for f in found
            ],
            span=span,
            skip_when=skip_when,
            verified={
                "matched": fit.matched,
                "expected": fit.expected,
                "precision": round(fit.precision, 4),
                "recall": round(fit.recall, 4),
            },
            provenance={"family_index": position},
        )
        records.append(entry)
        by_family[position] = entry

    spec = ParserSpec(schema_version=SCHEMA_VERSION, records=records, failures=failures)
    return spec, by_family


def build_spec(html: str, max_clusters: int = 10, min_cluster_size: int = 2) -> ParserSpec:
    root = stamp_uids(parse_html(html))
    clean = full_sanitize(root)
    index = build_index(root)

    document_ids = reused_ids(clean)
    candidates = filter_meaningful_candidates(list(clean.iter(etree.Element)), document_ids)
    clusters = [c for c in cluster_siblings(candidates, document_ids) if c.count >= min_cluster_size]
    ranked = rank_clusters(clusters)
    families = build_families(select_top_level_clusters(ranked, max_clusters=max_clusters), ranked)
    return specs_for_families(families, clean, root, index)[0]


def _header_values(elements, found) -> list[str] | None:
    """The literal header row, so the executor can skip it. Only meaningful
    when the field names were read off that row in the first place."""
    if not found or not all(f.name_source == "header_row" for f in found):
        return None

    anchors = set(elements)
    for element in elements:
        values = []
        for f in found:
            scope = scoped_element(element, f.sibling, anchors)
            if scope is None:
                values.append("")
                continue
            hits = relative_locator(f.locator)(scope) if f.locator else [scope]
            values.append(capture_value(hits[0] if hits else None, f.capture, f.attribute))
        if [slugify(v) for v in values] == [f.name for f in found]:
            return values
    return None


__all__ = ["build_spec", "specs_for_families"]
