"""Fase J: finding the record and a selector that reaches it.

The assertions here are about element SETS, not counts. A selector can
match the right number of wrong elements -- and did, before record
promotion existed: the pipeline's cluster element is an inner wrapper on
four of the six real pages, so a count-based check passed while the
overlap with the ground-truth records was exactly zero.
"""

from pathlib import Path

import pytest
import yaml
from lxml import etree
from lxml.cssselect import CSSSelector

from dom2parser.anchor import UID_ATTR, build_index, originals_for, stamp_uids
from dom2parser.cluster.families import build_families
from dom2parser.cluster.rank import rank_clusters, select_top_level_clusters
from dom2parser.cluster.siblings import cluster_siblings
from dom2parser.fingerprint.structural import filter_meaningful_candidates, reused_ids
from dom2parser.html_io import load_html_file, parse_html
from dom2parser.parser.build import build_spec
from dom2parser.parser.records import closure, completed_levels, promote
from dom2parser.parser.selector import synthesize
from dom2parser.sanitize import full_sanitize

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
GROUND_TRUTH = yaml.safe_load((Path(__file__).parent / "fixtures" / "ground_truth.yaml").read_text())

# The record-level entries of the ground truth: one repeated structure per
# page whose elements are the records a consumer would want. The other
# entries are field-level (`td.tituloLancamento`) or containers
# (`div.lancamentos`), which are not record boundaries and would fail this
# check for reasons that say nothing about synthesis.
RECORD_GROUND_TRUTH = {
    "bancodobrasil.html": "div.lancamentos table tr",
    "conjuntodadosgovbr.html": "div.search-result.container",
    "dadosabertrosfiocruz.html": "div.views-row",
    "folhadesp.html": "li.c-headline--newslist",
    # Each chat row is two identity-less divs inside the record; reaching
    # the record means climbing a shared parent (records.promote).
    "oss_gov_br_whatsapp.html": 'div[data-testid="cell-frame-container"]',
}


def _pipeline(path):
    root = stamp_uids(load_html_file(path))
    clean = full_sanitize(root)
    index = build_index(root)
    document_ids = reused_ids(clean)
    candidates = filter_meaningful_candidates(list(clean.iter(etree.Element)), document_ids)
    clusters = [c for c in cluster_siblings(candidates, document_ids) if c.count >= 2]
    ranked = rank_clusters(clusters)
    families = build_families(select_top_level_clusters(ranked, max_clusters=10), ranked)
    return root, clean, index, families, document_ids


def _uids(elements):
    return {el.get(UID_ATTR) for el in elements}


def _record_levels(family, clean, index, document_ids, cache):
    """Every promotion level, each re-closed the way `parser.build` does
    before synthesizing -- climbing can land on a level the seed did not
    fully cover, and the boundary is only judged once completed."""
    seed = originals_for(closure(family, clean, cache, document_ids), index)
    yield from completed_levels(seed, clean, index, build_index(clean), cache, document_ids)


@pytest.mark.parametrize("filename, selector", sorted(RECORD_GROUND_TRUTH.items()))
def test_some_family_reaches_the_ground_truth_record_set_exactly(filename, selector):
    root, clean, index, families, document_ids = _pipeline(EXAMPLES_DIR / filename)
    expected = _uids(CSSSelector(selector)(root))
    cache = {}

    reached = []
    for family in families:
        for level in _record_levels(family, clean, index, document_ids, cache):
            if _uids(level) == expected:
                reached.append(level)

    assert reached, (
        f"{filename}: no family, at any promotion level, covers the {len(expected)} elements "
        f"of {selector!r} -- records would be extracted from the wrong elements"
    )


@pytest.mark.parametrize("filename, selector", sorted(RECORD_GROUND_TRUTH.items()))
def test_synthesized_selector_for_the_ground_truth_records_is_exact(filename, selector):
    root, clean, index, families, document_ids = _pipeline(EXAMPLES_DIR / filename)
    expected = _uids(CSSSelector(selector)(root))
    cache = {}

    for family in families:
        for level in _record_levels(family, clean, index, document_ids, cache):
            if _uids(level) != expected:
                continue
            result = synthesize(level, root)
            assert result.ok, (
                f"{filename}: no selector reaches all {len(expected)} records; closest "
                f"{[(m.selector, round(m.recall, 2)) for m in result.near_misses]}"
            )
            assert _uids(CSSSelector(result.fit.selector)(root)) == expected, (
                f"{filename}: synthesized {result.fit.selector!r} matched "
                f"{result.fit.matched} elements against {len(expected)} expected "
                f"(precision {result.fit.precision:.2f})"
            )
            return


@pytest.mark.parametrize(
    "filename", sorted(p.name for p in EXAMPLES_DIR.glob("*.html")) if EXAMPLES_DIR.exists() else []
)
def test_every_emitted_record_selector_is_exact(filename):
    """A selector that over-matches without a rule explaining the overshoot
    must be reported as a failure, never emitted as a record -- a parser
    that half works is indistinguishable from one that works."""
    spec = build_spec((EXAMPLES_DIR / filename).read_text(errors="replace"))
    for record in spec.records:
        assert record.verified["precision"] == 1.0 and record.verified["recall"] == 1.0, (
            f"{filename}: emitted {record.selector!r} with precision "
            f"{record.verified['precision']} / recall {record.verified['recall']}"
        )


def test_promotion_climbs_a_record_divided_into_a_few_parts():
    """Downward fan-out: five records, each two anonymous divs. The family
    lands on the ten divs; the record is their parent."""
    root = stamp_uids(
        parse_html(
            "<ul>" + "".join(
                f"<li data-testid='row'><div><span>icon{i}</span></div><div><span>text{i}</span></div></li>"
                for i in range(5)
            ) + "</ul>"
        )
    )
    inner = [d for d in root.iter("div")]
    tags = [(level[0].tag, len(level)) for level in promote(inner)]
    assert ("li", 5) in tags, f"expected to climb from 10 divs to their 5 <li>, got {tags}"


def test_promotion_does_not_swallow_small_tables_into_their_tbody():
    """Two three-row tables: rows share a parent three at a time, which is
    within MAX_PARTS -- but two parents are a pair of containers, not a
    collection of records."""
    root = stamp_uids(
        parse_html(
            "<div>" + "".join(
                "<table class='t'><tbody>" + "".join(f"<tr><td>{t}{r}</td></tr>" for r in range(3)) + "</tbody></table>"
                for t in range(2)
            ) + "</div>"
        )
    )
    rows = list(root.iter("tr"))
    levels = promote(rows)
    assert [level[0].tag for level in levels] == ["tr"], (
        f"six rows in two tables must stay rows, got {[(l[0].tag, len(l)) for l in levels]}"
    )


def test_promotion_stops_where_siblings_share_a_parent():
    root = stamp_uids(
        parse_html("<ol><li class='row'><div class='w'><span>a</span></div></li>"
                   "<li class='row'><div class='w'><span>b</span></div></li></ol>")
    )
    spans = list(root.iter("span"))
    levels = promote(spans)
    tags = [level[0].tag for level in levels]
    assert tags == ["span", "div", "li"], (
        f"expected the climb to stop at <li> (both share the <ol>), got {tags}"
    )


def test_selector_excludes_a_state_class_that_separates_two_row_sets():
    root = stamp_uids(
        parse_html("<ul>" + "<li class='item'>a</li>" * 2 + "<li class='item is-hidden'>b</li>" * 3 + "</ul>")
    )
    visible = [el for el in root.iter("li") if "is-hidden" not in (el.get("class") or "")]
    result = synthesize(visible, root)
    assert result.ok and result.fit.precision == 1.0, (
        f"expected an exact selector for the 2 visible items, got "
        f"{result.fit.selector if result.ok else result.near_misses!r}"
    )
    assert len(CSSSelector(result.fit.selector)(root)) == 2
