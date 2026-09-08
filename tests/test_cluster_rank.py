"""Fase F: individual ranking signals, tested in isolation (per the plan's
risk mitigation for this heuristic component) using synthetic HTML shaped
like the real menu-vs-content contrast, plus one check against real data.
"""

from lxml.cssselect import CSSSelector
from pathlib import Path

from dom2parser.html_io import parse_html, load_html_file
from dom2parser.cluster.rank import (
    _distinct_semantic_descendant_count,
    _keyword_bonus_penalty,
    _recursive_informative_types,
    score_cluster,
)
from dom2parser.cluster.siblings import Cluster

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _cluster_of(elements):
    return Cluster(structural_key=(), content_signature=(), elements=list(elements))


def test_informative_types_signal_favors_data_bearing_records():
    root = parse_html(
        "<html><body>"
        '<div class="row"><span>18/07</span><span>Mercado</span><span>R$</span><span>52,74</span></div>'
        '<li class="menu-item"><a href="#">Sobre</a></li>'
        "</body></html>"
    )
    data_row = root.xpath('//div[@class="row"]')[0]
    menu_item = root.xpath('//li[@class="menu-item"]')[0]
    assert len(_recursive_informative_types(data_row)) >= 3  # DATE, CURRENCY, MONEY
    assert len(_recursive_informative_types(menu_item)) == 0


def test_distinct_semantic_descendant_count_favors_richer_records():
    root = parse_html(
        "<html><body>"
        '<div class="card"><h3 class="title">X</h3><p class="desc">Y</p>'
        '<span class="badge">Z</span></div>'
        '<li class="nav-item"><a href="#">Home</a></li>'
        "</body></html>"
    )
    card = root.xpath('//div[@class="card"]')[0]
    nav_item = root.xpath('//li[@class="nav-item"]')[0]
    assert _distinct_semantic_descendant_count(card) > _distinct_semantic_descendant_count(nav_item)


def test_keyword_bonus_penalty_distinguishes_content_from_nav_ancestor():
    root = parse_html(
        "<html><body>"
        '<div class="search-results"><div class="item">A</div></div>'
        '<nav class="main-menu"><div class="item">B</div></nav>'
        "</body></html>"
    )
    content_item, nav_item = root.xpath("//div[@class='item']")
    assert _keyword_bonus_penalty(content_item) > _keyword_bonus_penalty(nav_item)


def test_score_cluster_ranks_data_rows_above_menu_items():
    root = parse_html(
        "<html><body>"
        '<div id="content"><table><tr><td>18/07</td><td>Mercado A</td><td>R$</td><td>52,74</td></tr>'
        '<tr><td>19/07</td><td>Mercado B</td><td>R$</td><td>12,00</td></tr>'
        '<tr><td>20/07</td><td>Mercado C</td><td>R$</td><td>9,90</td></tr></table></div>'
        '<ul class="menu"><li><a href="#">Item 1</a></li><li><a href="#">Item 2</a></li>'
        '<li><a href="#">Item 3</a></li></ul>'
        "</body></html>"
    )
    rows = root.xpath("//tr")
    menu_items = root.xpath("//ul[@class='menu']/li")
    row_score = score_cluster(_cluster_of(rows)).score
    menu_score = score_cluster(_cluster_of(menu_items)).score
    assert row_score > menu_score


def test_real_ckan_cards_score_above_real_filter_options():
    root = load_html_file(EXAMPLES_DIR / "conjuntodadosgovbr.html")
    cards = CSSSelector("div.search-result.container")(root)
    options = CSSSelector("span.multiselect__option")(root)
    card_score = score_cluster(_cluster_of(cards)).score
    option_score = score_cluster(_cluster_of(options)).score
    assert card_score > option_score
