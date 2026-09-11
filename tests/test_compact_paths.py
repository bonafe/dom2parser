"""Per-segment volatility in ancestor paths: a per-instance id/testid
(list index, DB id, slug, random key) must collapse to `*` in both the
grouping key and the displayed path, while genuinely distinct named
locations must stay distinct.
"""

import pytest

from dom2parser.compact.paths import describe_path, location_key
from dom2parser.html_io import parse_html


def _rows(html, xpath):
    return parse_html(html).xpath(xpath)


def _wrapped_rows(wrapper_attrs: list[str]) -> list:
    html = "<div id='list'>" + "".join(
        f"<div {attrs}><div class='row'><span>a</span></div></div>" for attrs in wrapper_attrs
    ) + "</div>"
    return _rows(html, "//div[@class='row']")


@pytest.mark.parametrize(
    "attrs, expected_segment",
    [
        # digit run (virtualized list index)
        (["data-testid='list-item-%d'" % i for i in range(4)], 'div[data-testid="list-item-*"]'),
        # hex ids
        (["id='row-3f9a2c'", "id='row-e91b2d'", "id='row-0a1b2c'"], "div#row-*"),
        # UUID testids
        (
            [
                "data-testid='msg-6f1c2e4a-9b3d-4e5f-8a7b-1c2d3e4f5a6b'",
                "data-testid='msg-0a1b2c3d-4e5f-4a6b-9c8d-7e6f5a4b3c2d'",
            ],
            'div[data-testid="msg-*"]',
        ),
        # slugs: no digits at all, only sibling evidence + shared prefix
        (["id='item-apple'", "id='item-banana'", "id='item-cherry'"], "div#item-*"),
        # separator-less shared prefix, cut at the separator that exists
        (["id='user_john'", "id='user_jane'"], "div#user_*"),
        # random keys: no prefix, but every sibling looks generated
        (["id='Xk9pQ2'", "id='aB3dE5'", "id='Q7wErT9'"], "div#*"),
    ],
)
def test_per_instance_wrapper_identity_collapses_to_star(attrs, expected_segment):
    rows = _wrapped_rows(attrs)
    keys = {location_key(r) for r in rows}
    assert len(keys) == 1, "per-instance wrapper keys must not fragment the location"
    assert expected_segment in describe_path(rows[0])


def test_per_instance_id_on_the_element_itself():
    html = "<table><tbody>" + "".join(
        f"<tr id='tx-{k}'><td>a</td></tr>" for k in ("abc", "def", "ghi")
    ) + "</tbody></table>"
    rows = _rows(html, "//tr")
    assert len({location_key(r) for r in rows}) == 1
    assert describe_path(rows[0]).endswith("tr#tx-*")


def test_semantic_ids_differing_only_by_digit_merge_and_display_generalized():
    html = "".join(
        f"<div id='fatura{i}'><table><tr><td>a</td></tr></table></div>" for i in (1, 2)
    )
    rows = _rows(f"<div>{html}</div>", "//tr")
    assert len({location_key(r) for r in rows}) == 1
    assert "div#fatura*" in describe_path(rows[0])


def test_named_sibling_sections_stay_distinct():
    # `limites` vs `totalFatura` (bancodobrasil.html): sibling wrappers
    # with distinct class names are different places, not an enumeration.
    html = (
        "<td><div class='limites'><div class='textoItem'><span>a</span></div></div>"
        "<div class='totalFatura'><div class='textoItem'><span>a</span></div></div></td>"
    )
    items = _rows(html, "//div[@class='textoItem']")
    assert len({location_key(i) for i in items}) == 2


def test_sibling_ids_without_shared_prefix_stay_distinct():
    html = "".join(
        f"<div id='{name}'><table><tr><td>a</td></tr></table></div>" for name in ("header", "content", "footer")
    )
    rows = _rows(f"<div>{html}</div>", "//tr")
    assert len({location_key(r) for r in rows}) == 3
    assert "div#header" in describe_path(rows[0])


def test_prefix_equal_to_a_sibling_value_is_not_an_enumeration():
    # `#list` and `#list-header` are two named things, not `list*`.
    html = "<div id='list'><p>a</p></div><div id='list-header'><p>a</p></div>"
    ps = _rows(f"<div>{html}</div>", "//p")
    assert len({location_key(p) for p in ps}) == 2


def test_digits_in_tag_names_are_not_normalized():
    html = "<div><h2><span>a</span></h2><h3><span>a</span></h3></div>"
    spans = _rows(html, "//span")
    assert len({location_key(s) for s in spans}) == 2


def test_hex_shaped_english_words_survive():
    html = "<div id='facade'><p>a</p></div>"
    assert "div#facade" in describe_path(_rows(html, "//p")[0])


def test_utility_class_digits_are_masked_per_token():
    html = "<div class='tier-2 card'><p>a</p></div>"
    assert "div.card.tier-*" in describe_path(_rows(html, "//p")[0])


def test_cache_returns_same_segments():
    rows = _wrapped_rows(["id='item-a'", "id='item-b'"])
    cache: dict = {}
    assert location_key(rows[0], cache=cache) == location_key(rows[0])
    assert describe_path(rows[1], cache=cache) == describe_path(rows[1])
    assert cache
