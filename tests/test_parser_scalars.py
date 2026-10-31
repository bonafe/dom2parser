"""Fase N: a lone field located from one example of its value.

The property that matters is not that the sample reproduces -- every
candidate is checked for that -- but that the locator still finds the field
on the next page, where the value is different. So most tests synthesize on
one page and execute on a sibling page with the same layout and other values.
"""

import pytest
from lxml.etree import XPath

from dom2parser.html_io import parse_html
from dom2parser.parser.scalars import (
    execute_scalars,
    extract_scalar,
    synthesize_scalar,
    synthesize_scalars,
    value_pattern,
)
from dom2parser.parser.spec import ParserSpec, ScalarEntry

# Shaped after a card statement header: a label span + <br> + loose text,
# a label span followed by two peer value spans, label/value table cells,
# and a highlighted total that repeats the table's value.
STATEMENT = """
<html><body>
<table><tr>
  <td><div class="idCartao">
    <span class="tituloItem">&nbsp;Cartão</span><br>
    <span class="textoIdCartao">{card}</span><br>
    <span class="textoIdCartao">Nº&nbsp;{number}</span><br>
  </div></td>
  <td><div class="vencimentoFatura">
    <span class="tituloVencimento">Vencimento</span><br>
    {due}
  </div></td>
  <td><div class="caixaValorTotal">
    <div class="vtTitulo">Valor Total</div>
    <div class="vtMoeda">R$</div>
    <div class="vtValor">{total}</div>
  </div></td>
</tr></table>
<table class="resumo">
  <tr><td>Saldo anterior</td><td>{previous}</td></tr>
  <tr><td>Total da fatura - R$</td><td>{total}</td></tr>
</table>
<dl><dt>Melhor dia de compra</dt><dd>{best_day}</dd></dl>
</body></html>
"""

PAGE_A = dict(card="CARTAO AZUL", number="1234.XXXX.XXXX.5678", due="28/10/2026",
              total="13.405,63", previous="9.964,56", best_day="17")
PAGE_B = dict(card="CARTAO VERDE PLATINUM", number="9999.XXXX.XXXX.0001", due="05/01/2027",
              total="512,00", previous="1.000,10", best_day="3")

EXAMPLES = {
    "cartao": PAGE_A["card"],
    "numero": PAGE_A["number"],
    "vencimento": PAGE_A["due"],
    "total": PAGE_A["total"],
    "saldo_anterior": PAGE_A["previous"],
    "melhor_dia": PAGE_A["best_day"],
}
EXPECTED_B = {
    "cartao": PAGE_B["card"],
    "numero": PAGE_B["number"],
    "vencimento": PAGE_B["due"],
    "total": PAGE_B["total"],
    "saldo_anterior": PAGE_B["previous"],
    "melhor_dia": PAGE_B["best_day"],
}


def _page(values):
    return STATEMENT.format(**values)


@pytest.fixture(scope="module")
def entries():
    found, failures = synthesize_scalars(_page(PAGE_A), EXAMPLES)
    assert failures == []
    return {e.name: e for e in found}


def test_every_example_is_reproduced_on_the_sample(entries):
    assert execute_scalars(entries.values(), _page(PAGE_A)) == EXAMPLES


def test_the_locators_generalize_to_a_page_with_other_values(entries):
    assert execute_scalars(entries.values(), _page(PAGE_B)) == EXPECTED_B


def test_the_value_never_appears_in_the_locator_or_pattern(entries):
    for name, entry in entries.items():
        assert EXAMPLES[name] not in entry.locator
        assert EXAMPLES[name] not in (entry.pattern or "")


def test_label_cells_anchor_on_the_label_text(entries):
    total = entries["total"]
    assert total.strategy == "label"
    assert total.label in ("Total da fatura - R$", "Valor Total")
    assert entries["saldo_anterior"].label == "Saldo anterior"
    assert entries["melhor_dia"].label == "Melhor dia de compra"


def test_label_sharing_the_element_is_cut_by_the_shape_of_the_value(entries):
    due = entries["vencimento"]
    assert due.strategy == "prefix" and due.label == "Vencimento"
    assert due.pattern.startswith("Vencimento")


def test_a_peer_value_is_never_taken_for_a_label(entries):
    # The card number sits right after the card name; anchoring on the name
    # would pass here and fail on any other card.
    assert entries["numero"].label == "Cartão"
    assert entries["cartao"].label == "Cartão"


def test_a_missing_label_yields_empty_never_a_neighbouring_value(entries):
    changed = _page(PAGE_B).replace("Saldo anterior", "Saldo do mês passado")
    assert extract_scalar(entries["saldo_anterior"], parse_html(changed)) == ""


def test_example_absent_from_the_page_is_a_declared_failure():
    result = synthesize_scalar(parse_html(_page(PAGE_A)), "x", "não existe")
    assert not result.ok and result.reason == "example not found in the document"


def test_empty_example_is_a_declared_failure():
    assert synthesize_scalar(parse_html(_page(PAGE_A)), "x", "  ").reason == "empty example"


def test_class_is_used_when_there_is_no_label():
    html = '<div><p class="destaque">Aviso</p><span class="numeroProtocolo">AB-778812</span></div>'
    other = html.replace("AB-778812", "ZX-000001")
    result = synthesize_scalar(parse_html(html), "protocolo", "AB-778812")
    assert result.ok
    assert extract_scalar(result.entry, parse_html(other)) == "ZX-000001"


def test_label_with_quotes_becomes_a_valid_xpath_literal():
    html = """<table><tr><td>Cliente "VIP" d'Ouro</td><td>Sim senhor</td></tr></table>"""
    result = synthesize_scalar(parse_html(html), "vip", "Sim senhor")
    assert result.ok and result.entry.strategy == "label"
    XPath(result.entry.locator)  # compiles
    assert extract_scalar(result.entry, parse_html(html)) == "Sim senhor"


@pytest.mark.parametrize("text,value,pattern", [
    ("13.405,63", "13.405,63", None),
    ("Vencimento 28/10/2026", "28/10/2026", r"Vencimento\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)"),
    ("Saldo 1.000,00 Total -9,10", "-9,10", r"Total\s*([-+]?\d[\d.,]*)"),
    ("Nº 1234.XXXX", "1234.XXXX", r"Nº\s*(.+?)\s*$"),
    ("ACME LTDA CNPJ 00", "ACME LTDA", r"^\s*(.+?)\s*CNPJ"),
])
def test_value_pattern(text, value, pattern):
    assert value_pattern(text, value) == pattern


def test_spec_round_trip_keeps_scalars_and_old_specs_still_load(entries):
    spec = ParserSpec(schema_version=1, records=[], scalars=list(entries.values()))
    again = ParserSpec.from_json(spec.to_json())
    assert again.scalars == spec.scalars
    assert all(isinstance(s, ScalarEntry) for s in again.scalars)
    assert ParserSpec.from_dict({"schema_version": 1, "records": []}).scalars == []
