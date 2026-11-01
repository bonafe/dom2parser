"""Records grouped under a title that is not inside any of them.

Shaped after bancodobrasil.com.br's new account statement (synthetic data):
one card per day with the day's heading, then that day's entry lines. Each
line is `class="navigation" role="button"` (it opens the detail) and its
amount is `value positive` or `value negative`. Three things used to go
wrong, each on its own enough to lose most of the statement:

- the nav-keyword sanitizer removed every `navigation` line;
- the day cards clustered first and suppressed the lines inside them, so a
  day became one record with its lines as positional columns;
- the amount column was located by `negative`, the class of the typical
  line, and every incoming amount was missing from it.
"""

import dom2parser
from dom2parser.html_io import parse_html
from dom2parser.parser.executor import extract_records

DAYS = [
    ("30 de setembro, quarta", [("Saldo Anterior", "", "-R$ 100,00", "negative")]),
    ("01 de outubro, quinta", [("Recebimento de Proventos", "00.000.000/0001-00 ORGAO", "R$ 1.000,00", "positive"),
                               ("Pix - Recebido", "01/10 10:20 FULANA", "R$ 300,00", "positive"),
                               ("Pix - Enviado", "01/10 11:45 BELTRANO", "-R$ 400,00", "negative"),
                               ("Tarifa", "Cobrança referente 01/10", "-R$ 14,00", "negative")]),
    ("02 de outubro, sexta", [("Pix - Enviado", "02/10 21:18 CICLANO", "-R$ 180,00", "negative"),
                              ("Saldo do dia", "Conta-corrente", "R$ 606,00", "positive")]),
    ("05 de outubro, segunda", [("Pagto Energia", "CIA DE ENERGIA", "-R$ 104,77", "negative")]),
    ("07 de outubro, quarta", [("Pagamento de Telefone", "OPERADORA SA", "-R$ 74,32", "negative"),
                               ("Pix - Recebido", "07/10 09:39 FULANA", "R$ 50,00", "positive"),
                               ("Saldo do dia", "Conta-corrente", "R$ 476,91", "positive")]),
    ("09 de outubro, sexta", [("Pix - Enviado", "09/10 18:01 BELTRANA", "-R$ 75,00", "negative")]),
    ("13 de outubro, terça", [("Compra com Cartão", "13/10 10:50 MATERIAIS", "-R$ 6,00", "negative"),
                              ("Cashback", "Cashback Automático", "R$ 0,50", "positive")]),
    ("16 de outubro, sexta", [("Pagto cartão crédito", "CARTAO VISA", "-R$ 78,07", "negative")]),
]


def _line(label, detail, amount, sign):
    return (
        f'<div class="line-group"><div class="navigation line" role="button" tabindex="0">'
        f'<span class="label regular">{label}</span><span class="caption default">{detail}</span>'
        f'<span class="suffix"><span class="caption value large {sign}">{amount}</span></span>'
        f"</div></div>"
    )


def _statement() -> str:
    days = "".join(
        f'<div class="day"><div class="day-card"><h3 class="title default">{title}</h3></div>'
        f'<div class="statement-list">{"".join(_line(*l) for l in lines)}</div></div>'
        for title, lines in DAYS
    )
    return f'<html><body><nav class="menu"><a href="/">Início</a></nav><main class="extrato">{days}</main></body></html>'


EXPECTED = [(title, *line) for title, lines in DAYS for line in lines]


def _the_line_record():
    html = _statement()
    spec = dom2parser.compress(html).parser
    root = parse_html(html)
    for record in spec.records:
        rows = [r.values for r in extract_records(record, root) if not r.skipped]
        if len(rows) == len(EXPECTED):
            return record, rows
    raise AssertionError(f"no record with one row per line: {[(r.selector, r.count) for r in spec.records]}")


def test_every_line_is_a_record():
    record, rows = _the_line_record()
    labels = {f.name for f in record.fields}
    by_value = {v: k for k in labels for v in [rows[1][k]] if v}
    assert by_value["Recebimento de Proventos"] and by_value["00.000.000/0001-00 ORGAO"]


def test_amount_column_holds_incoming_and_outgoing():
    record, rows = _the_line_record()
    (amount,) = [f.name for f in record.fields if f.type == "MONEY"]
    assert [r[amount] for r in rows] == [e[3] for e in EXPECTED]


def test_each_line_carries_its_group_title():
    record, rows = _the_line_record()
    (title,) = [f for f in record.fields if f.axis == "preceding"]
    assert title.name == "group_title"
    assert [r[title.name] for r in rows] == [e[0] for e in EXPECTED]


def test_nav_class_on_an_item_role_is_not_navigation():
    from dom2parser.sanitize.boilerplate import _looks_like_nav

    root = parse_html('<div><div class="navigation" role="button">x</div><div class="sidebar" '
                      'role="complementary">y</div><div class="nav-links">z</div></div>')
    button, sidebar, links = root.xpath("//body/div/div")
    assert not _looks_like_nav(button) and _looks_like_nav(sidebar) and _looks_like_nav(links)


def test_records_without_groups_get_no_group_title():
    rows = "".join(f'<li class="item"><span class="name">P{i}</span><span class="price">R$ {i},00</span></li>'
                   for i in range(1, 9))
    html = f'<html><body><h2 class="title">Produtos</h2><ul class="products">{rows}</ul></body></html>'
    spec = dom2parser.compress(html).parser
    assert spec.records and not any(f.axis for r in spec.records for f in r.fields)
