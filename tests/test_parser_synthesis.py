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
from dom2parser.fingerprint.structural import filter_meaningful_candidates, generated_ids, reused_ids
from dom2parser.html_io import load_html_file, parse_html
from dom2parser.parser.build import build_spec
from dom2parser.parser.records import closure, promote
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
}

# oss_gov_br_whatsapp.html's chat rows are two identity-less sibling divs
# per row, so promotion cannot climb (parents are not injective) and the
# closure is 44 where the ground truth is 23. The near-miss report names
# `div[data-testid="cell-frame-container"]` explicitly, so the gap is
# visible rather than silent.
_KNOWN_FANOUT_LIMITATION = {"oss_gov_br_whatsapp.html"}


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


@pytest.mark.parametrize("filename, selector", sorted(RECORD_GROUND_TRUTH.items()))
def test_some_family_reaches_the_ground_truth_record_set_exactly(filename, selector):
    root, clean, index, families, document_ids = _pipeline(EXAMPLES_DIR / filename)
    expected = _uids(CSSSelector(selector)(root))
    cache = {}

    reached = []
    for family in families:
        elements = originals_for(closure(family, clean, cache, document_ids), index)
        for level in promote(elements):
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
        for level in promote(originals_for(closure(family, clean, cache, document_ids), index)):
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


def test_whatsapp_chat_rows_remain_a_declared_failure():
    """Documented limitation, asserted so it stays visible: the chat row is
    two identity-less sibling divs, so the record boundary cannot be
    climbed to and the closure is double the real row count."""
    filename = next(iter(_KNOWN_FANOUT_LIMITATION))
    root, clean, index, families, document_ids = _pipeline(EXAMPLES_DIR / filename)
    expected = _uids(CSSSelector('div[data-testid="cell-frame-container"]')(root))
    cache = {}
    reached = any(
        _uids(level) == expected
        for family in families
        for level in promote(originals_for(closure(family, clean, cache, document_ids), index))
    )
    assert not reached, (
        "whatsapp chat rows now reach the ground-truth set -- the fan-out limitation is "
        "fixed and this test plus the note in test_parser_synthesis should be removed"
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
