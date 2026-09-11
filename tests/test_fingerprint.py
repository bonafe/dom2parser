"""Fase C: fingerprint fallback validated against real elements from the
6 examples. The success criterion from the plan: no candidate cluster
produces a "trivially unique" fingerprint per instance once build-artifact
attributes and atomic-CSS classes are correctly ignored.
"""

from pathlib import Path

import pytest
from lxml.cssselect import CSSSelector

from dom2parser.html_io import load_html_file
from dom2parser.fingerprint.hashattrs import (
    find_uniform_build_artifact_attrs,
    looks_like_atomic_class_token,
)
from dom2parser.fingerprint.structural import compute_fingerprint, fingerprint_key, reused_ids

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _fingerprints_for(filename, selector):
    root = load_html_file(EXAMPLES_DIR / filename)
    build_artifacts = reused_ids(root)
    elements = CSSSelector(selector)(root)
    return [compute_fingerprint(el, build_artifacts) for el in elements]


# --- hashattrs.looks_like_atomic_class_token -------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "x78zum5", "x1n2onr6", "xh8yej3", "x5yr21d", "x10wlt62",
        # digit-free / vowel-rich Stylex hashes (oss_gov_br_whatsapp.html)
        "xeuugli", "xelbjmh", "xahtqtb", "x1liijdw", "x7coems",
        # React's `className={cond && "foo"}` rendered as a literal
        "false", "true", "undefined",
    ],
)
def test_stylex_atomic_classes_are_detected(token):
    assert looks_like_atomic_class_token(token)


def test_known_false_positive_x_prefixed_short_semantic_class_documented():
    """Documented limitation of the Stylex shape rule (`x` + 5-8 alnum):
    a real size modifier like `xlarge` is flagged as atomic too."""
    assert looks_like_atomic_class_token("xlarge")


@pytest.mark.parametrize(
    "token",
    [
        "lancamentos",
        "tituloLancamento",
        "search-result",
        "views-row",
        "c-headline--newslist",
        "col-2",
        "mb-5",
        "sf-depth-3",
    ],
)
def test_real_semantic_classes_are_not_flagged(token):
    assert not looks_like_atomic_class_token(token)


def test_known_false_positive_short_semantic_class_documented():
    """Documented limitation: a real, human-written class that happens to
    be short/digit-bearing/vowel-poor (bancodobrasil.html's "w100pct",
    meaning width:100%) is misclassified as atomic. Fingerprinting
    tolerates this because it falls back to other co-occurring classes or
    signals -- this test exists so the limitation stays visible instead of
    silently regressing to something worse."""
    assert looks_like_atomic_class_token("w100pct")


# --- hashattrs.find_uniform_build_artifact_attrs ---------------------------


def test_vue_scoped_css_hash_detected_as_build_artifact():
    root = load_html_file(EXAMPLES_DIR / "acervodadostecnicosgovbr.html")
    artifacts = find_uniform_build_artifact_attrs(root)
    assert "data-v-444d5111" in artifacts


# --- structural.compute_fingerprint / fingerprint_key ----------------------


def test_acervo_resource_rows_share_one_fingerprint():
    fps = _fingerprints_for("acervodadostecnicosgovbr.html", "div.row.flex.mb-5")
    assert len(fps) == 28
    keys = {fingerprint_key(fp) for fp in fps}
    assert len(keys) == 1


def test_ckan_result_cards_share_one_fingerprint():
    fps = _fingerprints_for("conjuntodadosgovbr.html", "div.search-result.container")
    assert len(fps) == 10
    keys = {fingerprint_key(fp) for fp in fps}
    assert len(keys) == 1


def test_fiocruz_views_rows_share_one_fingerprint():
    fps = _fingerprints_for("dadosabertrosfiocruz.html", "div.views-row")
    assert len(fps) == 12
    keys = {fingerprint_key(fp) for fp in fps}
    assert len(keys) == 1


def test_whatsapp_chat_rows_use_testid_and_share_one_fingerprint():
    fps = _fingerprints_for(
        "oss_gov_br_whatsapp.html", 'div[data-testid="cell-frame-container"]'
    )
    assert len(fps) == 23
    assert all(fp.identity[0] == "testid" for fp in fps)
    keys = {fingerprint_key(fp) for fp in fps}
    assert len(keys) == 1


def test_whatsapp_atomic_classes_do_not_leak_into_identity():
    """Even though every chat row also carries 5-25 Stylex atomic classes,
    those must never end up selected as the identity signal (data-testid
    is available and must win)."""
    fps = _fingerprints_for(
        "oss_gov_br_whatsapp.html", 'div[data-testid="cell-frame-container"]'
    )
    for fp in fps:
        assert fp.identity[0] != "class"
