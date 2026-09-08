"""Fase G: representative_indices covers first/second/middle/penultimate/
last without going out of bounds on small clusters, and sample_cluster
combines representative positions with real outliers found via
cluster.outliers (bancodobrasil.html's transaction cluster)."""

from pathlib import Path

import pytest
from lxml.cssselect import CSSSelector

from dom2parser.html_io import load_html_file
from dom2parser.cluster.siblings import cluster_siblings
from dom2parser.sampling.representative import representative_indices, sample_cluster

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 5, 10, 122])
def test_representative_indices_within_bounds_and_deduplicated(n):
    idx = representative_indices(n)
    assert all(0 <= i < n for i in idx)
    if n > 0:
        assert 0 in idx
        assert (n - 1) in idx


def test_sample_cluster_includes_min_max_money_outlier():
    root = load_html_file(EXAMPLES_DIR / "bancodobrasil.html")
    rows = CSSSelector("div.lancamentos table tr")(root)
    four_td = [r for r in rows if len(r.findall("td")) == 4]
    clusters = cluster_siblings(four_td)
    txn = next(c for c in clusters if c.content_signature == ("DATE", "TEXT", "CURRENCY", "MONEY"))

    sample = sample_cluster(txn)
    values = [el.findall("td")[3].text_content().strip() for el in sample.elements]
    assert any("-11.966,18" in v for v in values)
    assert len(sample.indices) < txn.count  # a real compression, not the whole cluster


def test_sample_cluster_max_samples_cap_prefers_representative_positions():
    root = load_html_file(EXAMPLES_DIR / "bancodobrasil.html")
    rows = CSSSelector("div.lancamentos table tr")(root)
    four_td = [r for r in rows if len(r.findall("td")) == 4]
    clusters = cluster_siblings(four_td)
    txn = next(c for c in clusters if c.content_signature == ("DATE", "TEXT", "CURRENCY", "MONEY"))

    sample = sample_cluster(txn, max_samples=3)
    assert len(sample.indices) <= 3
    assert 0 in sample.indices
