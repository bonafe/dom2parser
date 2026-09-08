"""Fase D: content signature always comes from text, never from class, and
degrades gracefully. Uses real text samples pulled from the 6 examples."""

import pytest

from dom2parser.content.signature import classify


@pytest.mark.parametrize(
    "text,expected_type",
    [
        ("", "EMPTY"),
        ("   ", "EMPTY"),
        ("18/07", "DATE"),  # bancodobrasil.html transaction date (no year)
        ("28/07", "DATE"),
        ("29/09/2021", "DATE"),  # acervodadostecnicosgovbr.html catalogacao date
        ("R$", "CURRENCY"),
        ("52,74", "MONEY"),
        ("12.676,08", "MONEY"),  # bancodobrasil.html SALDO FATURA ANTERIOR value
        ("Supermercados", "TEXT"),  # tituloLancamento category label
        ("MERCADO OLIVEIRA", "TEXT"),
        ("CSV", "FILE_FORMAT"),
        ("PDF", "FILE_FORMAT"),
        ("48 Downloads", "COUNT_LABELED"),
        ("0 Seguidores", "COUNT_LABELED"),
        ("2561 Downloads", "COUNT_LABELED"),
        (
            "Indisponível (Cabeçalho 'Last-modified' não encontrado ou inválido)",
            "TEXT",
        ),  # degraded date field -- must not crash or be forced into DATE
        ("contato@example.com", "EMAIL"),
        ("https://dados.gov.br/dataset/x", "URL"),
        ("21:31", "TIME"),
        ("45%", "PERCENTAGE"),
        ("123", "INTEGER"),
        ("1.234", "INTEGER"),
        ("12,5", "DECIMAL"),
    ],
)
def test_classify_type(text, expected_type):
    assert classify(text).type == expected_type


def test_count_labeled_parses_count_and_label():
    sig = classify("48 Downloads")
    assert sig.value == (48, "Downloads")


def test_same_class_different_content_yields_different_signature_types():
    """The CKAN finding this module exists for: `search-result-metadata`
    backs both a file format and a labeled count -- signature must depend
    only on the text, not on the (identical) class name."""
    assert classify("CSV").type == "FILE_FORMAT"
    assert classify("48 Downloads").type == "COUNT_LABELED"


def test_classify_never_raises_on_arbitrary_text():
    weird_inputs = [None, "", "   \n\t ", "R$ 52,74 extra text", "-", "N/A", "??"]
    for text in weird_inputs:
        sig = classify(text)
        assert sig.type  # always produces some type, never raises
