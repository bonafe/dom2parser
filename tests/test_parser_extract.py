"""Fases K-M: fields, the serialized parser, and running it.

The end-to-end case is bancodobrasil.html, because it is the one page in
the corpus that carries its own column names -- the spec's worked example
asks for exactly `Data | Transações | Moeda | Valor`, and getting those
without a language model is the whole claim of this stage.
"""

from pathlib import Path

import pytest

from dom2parser.anchor import stamp_uids
from dom2parser.html_io import parse_html
from dom2parser.parser.build import build_spec
from dom2parser.parser.executor import execute
from dom2parser.parser.fields import discover
from dom2parser.parser.naming import slugify
from dom2parser.parser.spec import SCHEMA_VERSION, ParserSpec
from dom2parser.parser.validate import validate

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

_TABLE = """
<table><tbody>
  <tr><td>Data</td><td>Transações</td><td>Moeda</td><td>Valor</td></tr>
  <tr><td>18/07</td><td>MERCADO OLIVEIRA</td><td>R$</td><td>52,74</td></tr>
  <tr><td>28/07</td><td>PGTO DEBITO CONTA</td><td>R$</td><td>-11.966,18</td></tr>
  <tr><td>17/07</td><td>Supermercado BR</td><td>R$</td><td>135,47</td></tr>
</tbody></table>
"""


def _rows(html):
    root = stamp_uids(parse_html(html))
    return root, list(root.iter("tr"))


def test_field_names_are_read_off_a_header_row():
    _, rows = _rows(_TABLE)
    fields = discover(rows)
    assert [f.name for f in fields] == ["data", "transacoes", "moeda", "valor"], (
        f"expected the header row to name the columns, got {[f.name for f in fields]}"
    )
    assert {f.name_source for f in fields} == {"header_row"}


def test_field_types_come_from_the_content_classifier():
    _, rows = _rows(_TABLE)
    assert [f.type for f in discover(rows)] == ["DATE", "TEXT", "CURRENCY", "MONEY"]


def test_a_link_field_captures_its_href_not_its_text():
    """`direct_children_text` throws attributes away, which is why link
    extraction is impossible from the compact representation alone."""
    root = stamp_uids(
        parse_html(
            "<ul>"
            "<li class='r'><a href='/a'>first</a><span>alpha</span></li>"
            "<li class='r'><a href='/b'>second</a><span>beta</span></li>"
            "</ul>"
        )
    )
    fields = discover(list(root.iter("li")))
    by_capture = {(f.locator, f.capture): f for f in fields}
    link = next(f for f in fields if f.capture == "attr")
    assert link.attribute == "href", f"expected href capture, got {link.attribute!r}"
    # The same link also yields its visible text, as a sibling column named
    # after it -- `first`/`second` is a value too, not just the destination.
    assert (link.locator, "text") in by_capture, f"link text column missing: {[(f.name, f.capture) for f in fields]}"
    assert link.name.endswith("_url"), f"attribute column should carry the text column's name plus a suffix, got {link.name!r}"


def test_a_field_missing_from_some_records_is_optional():
    root = stamp_uids(
        parse_html(
            "<ul>"
            "<li class='r'><span class='n'>a</span><span class='opt'>x</span></li>"
            "<li class='r'><span class='n'>b</span></li>"
            "<li class='r'><span class='n'>c</span><span class='opt'>y</span></li>"
            "<li class='r'><span class='n'>d</span></li>"
            "</ul>"
        )
    )
    fields = {f.name: f for f in discover(list(root.iter("li")))}
    optional = [f for f in fields.values() if not f.required]
    assert optional and optional[0].present == 2 and optional[0].total == 4, (
        f"expected an optional field present in 2 of 4 records, got "
        f"{[(f.name, f.present, f.total) for f in fields.values()]}"
    )


def test_a_field_seen_in_a_single_record_is_not_a_field():
    """The same bar `min_cluster_size` sets for structures: once is not a
    pattern. This is what keeps a table's `th` header cells from becoming
    fields of its data rows."""
    root = stamp_uids(
        parse_html(
            "<ul>"
            "<li class='r'><span class='n'>a</span><span class='once'>x</span></li>"
            "<li class='r'><span class='n'>b</span></li>"
            "<li class='r'><span class='n'>c</span></li>"
            "</ul>"
        )
    )
    names = [f.name for f in discover(list(root.iter("li")))]
    assert "once" not in names, f"a value seen in one of three records became a field: {names}"


def test_a_constant_prose_column_is_dropped_but_a_constant_currency_is_kept():
    """`R$` repeats in every row of a statement and is still a field;
    `Salvar para ler depois` repeats on every card and is furniture. The
    rule that separates them is the content type, not the repetition."""
    _, rows = _rows(_TABLE)
    names = [f.name for f in discover(rows)]
    assert "moeda" in names, f"constant CURRENCY column was pruned: {names}"


def test_slugify_folds_accents_to_an_identifier():
    assert slugify("Transações") == "transacoes"
    assert slugify("Data de Atualização") == "data_de_atualizacao"


def test_spec_round_trips_through_yaml_and_json():
    _, rows = _rows(_TABLE)
    spec = build_spec(_TABLE)
    assert spec.schema_version == SCHEMA_VERSION
    for text, loader in ((spec.to_yaml(), ParserSpec.from_yaml), (spec.to_json(), ParserSpec.from_json)):
        assert loader(text).to_dict() == spec.to_dict()


def test_executor_skips_the_header_row_it_named_the_fields_from():
    spec = build_spec(_TABLE)
    record = spec.records[0]
    extraction = execute(spec, _TABLE)[record.name]
    assert len(extraction.records) == 4 and len(extraction.kept) == 3, (
        f"expected 4 rows with the header skipped, got "
        f"{len(extraction.records)} matched / {len(extraction.kept)} kept"
    )
    assert [r.skip_reason for r in extraction.records if r.skipped] == ["header_row"]


def test_extracted_values_are_keyed_by_derived_field_name():
    spec = build_spec(_TABLE)
    record = spec.records[0]
    first = execute(spec, _TABLE)[record.name].kept[0]
    assert first.values == {
        "data": "18/07",
        "transacoes": "MERCADO OLIVEIRA",
        "moeda": "R$",
        "valor": "52,74",
    }


@pytest.mark.skipif(not (EXAMPLES_DIR / "bancodobrasil.html").exists(), reason="corpus is local-only")
def test_bancodobrasil_statement_extracts_named_transactions():
    html = (EXAMPLES_DIR / "bancodobrasil.html").read_text(errors="replace")
    spec = build_spec(html)
    record = next(r for r in spec.records if r.selector == "div.lancamentos tr")

    assert [f.name for f in record.fields] == ["data", "transacoes", "moeda", "valor"], (
        f"column names should come off the statement's own header row, got "
        f"{[(f.name, f.name_source) for f in record.fields]}"
    )
    assert record.verified == {"matched": 154, "expected": 154, "precision": 1.0, "recall": 1.0}

    report = validate(record, execute(spec, html)[record.name])
    dated = next(m for m in report.fields if m.name == "data")
    assert dated.present == 123 and dated.conforming == dated.present, (
        f"expected 123 rows carrying a conforming date, got {dated.present} present / "
        f"{dated.conforming} conforming"
    )
    # 154 matched: 2 header rows and 13 all-empty spacer rows are skipped,
    # each reported with its reason rather than dropped.
    assert report.skipped == 15
    assert report.as_text().startswith("registros encontrados: 139")


_GLOSSARY = """
<dl class="glossary">
  <dt id="term-abc">abstract base class<a class="headerlink" href="#term-abc">¶</a></dt>
  <dd><p>A class that cannot be instantiated.</p></dd>
  <dt id="term-arg">argument<a class="headerlink" href="#term-arg">¶</a></dt>
  <dd><p>A value passed to a function.</p></dd>
  <dt id="term-bdfl">BDFL<a class="headerlink" href="#term-bdfl">¶</a></dt>
  <dt id="term-bdfl2">benevolent dictator<a class="headerlink" href="#term-bdfl2">¶</a></dt>
  <dd><p>Guido.</p></dd>
  <dt id="term-cls">class<a class="headerlink" href="#term-cls">¶</a></dt>
  <dd><p>A template for objects.</p></dd>
</dl>
"""


def test_a_record_spread_over_sibling_pairs_is_one_record():
    """A definition list spreads each entry over `dt` + `dd`. The family
    the pipeline finds may be the `dd`; the record must still be the `dt`
    (it carries the id) with the definition as a field, and two terms
    sharing one definition must not borrow the next entry's."""
    spec = build_spec(_GLOSSARY)
    record = next(r for r in spec.records if r.span == 2)
    assert record.selector.endswith("dt"), f"anchor should be the term, got {record.selector!r}"
    names = {f.name: f for f in record.fields}
    assert "term" in names and "definition" in names, f"got {sorted(names)}"
    assert names["term"].sibling == 0 and names["definition"].sibling == 1

    kept = execute(spec, _GLOSSARY)[record.name].kept
    by_term = {r.values["term"]: r.values["definition"] for r in kept}
    assert by_term["abstract base class"] == "A class that cannot be instantiated."
    assert by_term["BDFL"] == "", "a term whose dd belongs to the next dt must not take it"
    assert by_term["benevolent dictator"] == "Guido."


def test_permalink_glyph_is_not_part_of_the_term():
    spec = build_spec(_GLOSSARY)
    record = next(r for r in spec.records if r.span == 2)
    terms = [r.values["term"] for r in execute(spec, _GLOSSARY)[record.name].kept]
    assert "¶" not in "".join(terms), terms


def test_hacker_news_style_three_row_items_are_one_record():
    html = "<table><tbody>" + "".join(
        f"<tr class='athing' id='{i}'><td class='title'><span class='titleline'><a href='/{i}'>Story {i}</a></span></td></tr>"
        f"<tr><td class='subtext'><span class='score'>{i * 10} points</span> by <a class='hnuser'>user{i}</a></td></tr>"
        f"<tr class='spacer'></tr>"
        for i in range(1, 6)
    ) + "</tbody></table>"
    spec = build_spec(html)
    record = next(r for r in spec.records if r.span == 3)
    assert record.selector == "tr.athing", record.selector
    values = execute(spec, html)[record.name].kept[0].values
    assert values["titleline"] == "Story 1" and values["score"] == "10 points", values
