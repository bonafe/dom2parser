"""Fase 1b unit tests with synthetic HTML.

None of the 6 real examples exercises dedup_identical_subtrees in
isolation anymore: their one real case of massive identical-subtree
duplication (Folha's 484 repeated share-icon SVGs) is already eliminated
by strip.strip_tags removing all <svg> outright, before this step runs.
These synthetic cases validate the mechanism directly.
"""

from lxml import etree

from dom2parser.html_io import parse_html
from dom2parser.sanitize.dedup_subtree import dedup_identical_subtrees


def _make_html(n_icons: int, n_records: int) -> str:
    icons = "".join(
        f'<div class="card"><i class="icon-share-outline-large-decorative"></i>'
        f"<p>Item {i}</p></div>"
        for i in range(n_records)
    )
    return f"<html><body>{icons}</body></html>"


def test_large_scale_identical_decoration_is_collapsed():
    html = _make_html(n_icons=0, n_records=60)
    root = parse_html(html)
    removed = dedup_identical_subtrees(root, min_len=10, min_count=50)
    icons = root.xpath('//i[contains(@class, "icon-share")]')
    assert removed > 0
    # exactly one real icon element should survive, the rest replaced by
    # lightweight <template-ref> placeholders.
    assert len(icons) == 1
    assert icons[0].get("data-dedup-count") == "60"
    refs = root.xpath("//template-ref")
    assert len(refs) == 59
    # the varying text content (the actual record data) must be untouched.
    texts = root.xpath("//p/text()")
    assert texts[0] == "Item 0"
    assert texts[-1] == "Item 59"


def test_small_scale_identical_content_is_not_collapsed():
    """Below min_count, byte-identical elements (e.g. constant-label
    buttons or empty spacer cells that are still real per-record fields)
    must survive untouched -- this is the acervodadostecnicosgovbr.html /
    bancodobrasil.html regression this test guards against."""
    html = "".join(f'<button class="download">Acessar</button>' for _ in range(10))
    root = parse_html(f"<html><body>{html}</body></html>")
    removed = dedup_identical_subtrees(root, min_len=10, min_count=50)
    assert removed == 0
    assert len(root.xpath("//button")) == 10
