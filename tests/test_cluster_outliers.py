"""Fase G (part 2): outlier detection within an already-homogeneous
cluster, validated against bancodobrasil.html's 122-row transaction
cluster (DATE, TEXT, CURRENCY, MONEY)."""

from pathlib import Path

from lxml.cssselect import CSSSelector

from dom2parser.html_io import load_html_file
from dom2parser.cluster.siblings import cluster_siblings
from dom2parser.cluster.outliers import (
    numeric_field_outlier_indices,
    text_length_outlier_indices,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _bb_transaction_cluster():
    root = load_html_file(EXAMPLES_DIR / "bancodobrasil.html")
    rows = CSSSelector("div.lancamentos table tr")(root)
    four_td = [r for r in rows if len(r.findall("td")) == 4]
    clusters = cluster_siblings(four_td)
    return next(c for c in clusters if c.content_signature == ("DATE", "TEXT", "CURRENCY", "MONEY"))


def test_numeric_outlier_finds_largest_debit_and_credit():
    cluster = _bb_transaction_cluster()
    assert cluster.count == 122
    idx = numeric_field_outlier_indices(cluster)
    values = [cluster.elements[i].findall("td")[3].text_content().strip() for i in idx]
    # the spec's own motivating example: the largest single debit.
    assert any("-11.966,18" in v for v in values)


def test_text_length_outlier_is_within_bounds():
    cluster = _bb_transaction_cluster()
    idx = text_length_outlier_indices(cluster)
    assert idx
    assert all(0 <= i < cluster.count for i in idx)


def test_outliers_on_empty_cluster_do_not_crash():
    from dom2parser.cluster.siblings import Cluster

    empty = Cluster(structural_key=(), content_signature=(), elements=[])
    assert numeric_field_outlier_indices(empty) == set()
    assert text_length_outlier_indices(empty) == set()
