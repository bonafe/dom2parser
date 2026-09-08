"""Fase B: full_sanitize keeps the relevant content in each example intact
while removing the dominant boilerplate/noise cluster annotated in
ground_truth.yaml.
"""

from pathlib import Path

import pytest
from lxml.cssselect import CSSSelector

from dom2parser.html_io import load_html_file
from dom2parser.sanitize import full_sanitize
from dom2parser.sanitize.strip import sanitize as basic_sanitize
from dom2parser.compact.tokens import reduction_report
from lxml import etree

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _sanitized(filename):
    root = load_html_file(EXAMPLES_DIR / filename)
    return full_sanitize(root)


@pytest.mark.parametrize("filename", [p.name for p in EXAMPLES_DIR.glob("*.html")])
def test_full_sanitize_does_not_crash_and_shrinks(filename):
    original = (EXAMPLES_DIR / filename).read_text(encoding="utf-8", errors="ignore")
    clean = _sanitized(filename)
    clean_text = etree.tostring(clean, encoding="unicode", method="html")
    report = reduction_report(original, clean_text)
    assert report["reduction_pct"]["chars"] > 0


def test_bancodobrasil_relevant_content_survives_and_menu_removed():
    clean = _sanitized("bancodobrasil.html")
    assert len(CSSSelector("div.lancamentos")(clean)) == 2
    assert len(CSSSelector("td.tituloLancamento")(clean)) == 33
    assert len(CSSSelector("*.menu-titulo-nivel2")(clean)) == 0


def test_acervo_relevant_content_survives():
    clean = _sanitized("acervodadostecnicosgovbr.html")
    assert len(CSSSelector("div.row.flex.mb-5")(clean)) == 28
    assert len(CSSSelector("#btnDownloadUrl")(clean)) == 28


def test_ckan_relevant_content_survives_and_filter_widget_removed():
    clean = _sanitized("conjuntodadosgovbr.html")
    assert len(CSSSelector("div.search-result.container")(clean)) == 10
    assert len(CSSSelector("span.multiselect__option")(clean)) == 0
    assert len(CSSSelector("li.multiselect__element")(clean)) == 0


def test_fiocruz_relevant_content_survives_and_megamenu_removed():
    clean = _sanitized("dadosabertrosfiocruz.html")
    assert len(CSSSelector("div.views-row")(clean)) == 12
    assert len(CSSSelector("li[class*=sf-depth]")(clean)) == 0


def test_folha_newslist_survives_including_hidden_pagination_and_menu_removed():
    clean = _sanitized("folhadesp.html")
    # all 100 items must survive, including the 70 lazily-paginated ones,
    # since those are real data, not boilerplate.
    assert len(CSSSelector("li.c-headline--newslist")(clean)) == 100
    assert len(CSSSelector("li.c-list-menu__item")(clean)) == 0
    assert len(CSSSelector("svg")(clean)) == 0


def test_whatsapp_relevant_content_survives_and_bootstrap_json_removed():
    clean = _sanitized("oss_gov_br_whatsapp.html")
    assert len(CSSSelector('div[data-testid="cell-frame-container"]')(clean)) == 23
    assert len(CSSSelector('div[data-testid="msg-container"]')(clean)) == 6
    assert len(CSSSelector("script[data-sjs]")(clean)) == 0


def test_noisy_attrs_removed():
    clean = _sanitized("bancodobrasil.html")
    for el in clean.iter():
        assert "style" not in el.attrib
        assert not any(k.lower().startswith("on") for k in el.attrib)
