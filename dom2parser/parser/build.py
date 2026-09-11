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

from ..anchor import build_index, originals_for, stamp_uids
from ..cluster.families import build_families
from ..cluster.rank import rank_clusters, select_top_level_clusters
from ..cluster.siblings import cluster_siblings
from ..fingerprint.hashattrs import find_uniform_build_artifact_attrs
from ..fingerprint.structural import filter_meaningful_candidates
from ..html_io import parse_html
from ..sanitize import full_sanitize
from .fields import discover
from .naming import slugify
from .records import closure, promote
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


def _best_level(family, clean, root, index, cache):
    """The outermost promotion level with an exact selector."""
    elements = originals_for(closure(family, clean, cache), index)
    if not elements:
        return None, None, ()

    best, inexact = None, []
    for level in promote(elements):
        result = synthesize(level, root)
        if not result.ok:
            inexact.extend(result.near_misses)
        elif result.fit.precision == 1.0:
            best = (level, result.fit)
        else:
            inexact.append(result.fit)
    if best is None:
        inexact.sort(key=lambda f: (-f.recall, -f.precision, len(f.selector)))
        return None, None, tuple(inexact[:MAX_REPORTED_MISSES])
    return best[0], best[1], ()


def build_spec(html: str, max_clusters: int = 10, min_cluster_size: int = 2) -> ParserSpec:
    root = stamp_uids(parse_html(html))
    clean = full_sanitize(root)
    index = build_index(root)

    artifacts = find_uniform_build_artifact_attrs(clean)
    candidates = filter_meaningful_candidates(list(clean.iter(etree.Element)), artifacts)
    clusters = [c for c in cluster_siblings(candidates, artifacts) if c.count >= min_cluster_size]
    ranked = rank_clusters(clusters)
    families = build_families(select_top_level_clusters(ranked, max_clusters=max_clusters), ranked)

    cache: dict = {}
    records, failures, taken = [], [], set()
    for family in families:
        elements, fit, near_misses = _best_level(family, clean, root, index, cache)
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

        found = discover(elements)
        header_values = _header_values(elements, found)
        skip_when = {"header_values": header_values} if header_values else {}

        records.append(
            RecordEntry(
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
                    )
                    for f in found
                ],
                skip_when=skip_when,
                verified={
                    "matched": fit.matched,
                    "expected": fit.expected,
                    "precision": round(fit.precision, 4),
                    "recall": round(fit.recall, 4),
                },
            )
        )

    return ParserSpec(schema_version=SCHEMA_VERSION, records=records, failures=failures)


def _header_values(elements, found) -> list[str] | None:
    """The literal header row, so the executor can skip it. Only meaningful
    when the field names were read off that row in the first place."""
    if not found or not all(f.name_source == "header_row" for f in found):
        return None
    from .fields import _relative, _value_of

    locators = [(_relative(f.locator), f.attribute) for f in found]
    for element in elements:
        values = []
        for xpath, attribute in locators:
            hits = xpath(element)
            values.append(_value_of(hits[0], attribute) if hits else "")
        if [slugify(v) for v in values] == [f.name for f in found]:
            return values
    return None


__all__ = ["build_spec"]
