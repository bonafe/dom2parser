"""Fase E: clustering tolerant to optional fields, validated against real
elements from bancodobrasil.html (structural clash resolved by content
signature) and conjuntodadosgovbr.html (optional field must not fragment
the cluster).
"""

from pathlib import Path

from lxml.cssselect import CSSSelector

from dom2parser.html_io import load_html_file
from dom2parser.fingerprint.structural import reused_ids
from dom2parser.cluster.siblings import (
    cluster_siblings,
    group_by_fingerprint,
    optional_fields,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_ckan_result_cards_form_a_single_cluster_despite_optional_badge():
    root = load_html_file(EXAMPLES_DIR / "conjuntodadosgovbr.html")
    cards = CSSSelector("div.search-result.container")(root)
    assert len(cards) == 10

    groups = group_by_fingerprint(cards)
    assert len(groups) == 1, "optional quality-badge field must not fragment the structural group"

    clusters = cluster_siblings(cards)
    assert len(clusters) == 1
    assert clusters[0].count == 10


def test_ckan_quality_badge_detected_as_optional_field_present_in_6_of_10():
    root = load_html_file(EXAMPLES_DIR / "conjuntodadosgovbr.html")
    cards = CSSSelector("div.search-result.container")(root)
    clusters = cluster_siblings(cards)
    assert len(clusters) == 1

    fields = optional_fields(clusters[0])
    bronze_keys = [key for key in fields if "seloBronze" in str(key)]
    assert len(bronze_keys) == 1
    assert fields[bronze_keys[0]] == 6  # confirmed empirically: present in 6/10 cards


def test_bancodobrasil_rows_share_dom_shape_but_split_by_content_signature():
    """The spec's own motivating case: transaction/section/empty rows are
    all tr(td, td, td, td) with no distinguishing class -- DOM fingerprint
    alone must NOT tell them apart (single structural group), but content
    signature must."""
    root = load_html_file(EXAMPLES_DIR / "bancodobrasil.html")
    rows = CSSSelector("div.lancamentos table tr")(root)
    assert len(rows) == 154

    groups = group_by_fingerprint(rows)
    # every row kind (header/transaction/section/empty/special) has the
    # same tag+children shape, so they must all land in one structural key.
    four_td_rows = [r for r in rows if len(r.findall("td")) == 4]
    four_td_groups = group_by_fingerprint(four_td_rows)
    assert len(four_td_groups) == 1

    clusters = cluster_siblings(four_td_rows)
    # but multiple distinct content-signature sub-clusters must emerge.
    assert len(clusters) > 1

    signatures = {c.content_signature for c in clusters}
    assert ("EMPTY", "EMPTY", "EMPTY", "EMPTY") in signatures  # spacer rows
    money_like = [s for s in signatures if s[-1] == "MONEY"]
    assert money_like, "at least one row kind should end in a MONEY column"


def test_acervo_resource_rows_single_cluster_full_count():
    root = load_html_file(EXAMPLES_DIR / "acervodadostecnicosgovbr.html")
    build_artifacts = reused_ids(root)
    rows = CSSSelector("div.row.flex.mb-5")(root)
    clusters = cluster_siblings(rows, build_artifacts)
    assert sum(c.count for c in clusters) == 28
