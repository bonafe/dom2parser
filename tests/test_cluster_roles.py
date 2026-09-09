"""`classify_role` uses structural signals (field-count/type degradation
vs. the family's primary signature) as its primary rule, with a small
cross-locale keyword list only as a secondary, non-load-bearing signal --
tested here with both the real bancodobrasil.html-derived signatures and
deliberately generic, non-Portuguese/non-banking synthetic ones, to prove
the classifier doesn't implicitly depend on language or a specific field
order.
"""

from dom2parser.cluster.roles import (
    ROLE_EMPTY,
    ROLE_SECTION,
    ROLE_SUMMARY,
    ROLE_VARIANT,
    classify_role,
)

BB_PRIMARY = ("DATE", "TEXT", "CURRENCY", "MONEY")


def test_all_empty_signature_is_empty_role():
    assert classify_role(("EMPTY", "EMPTY", "EMPTY", "EMPTY"), BB_PRIMARY) == ROLE_EMPTY


def test_single_text_field_is_section_role():
    # bancodobrasil.html's category-header rows: "Restaurantes", "Saúde", ...
    assert classify_role(("EMPTY", "TEXT", "EMPTY", "EMPTY"), BB_PRIMARY) == ROLE_SECTION


def test_type_degradation_alone_is_summary_role_without_keyword():
    # bancodobrasil.html's SALDO FATURA ANTERIOR/SubTotal/Total rows -- the
    # DATE field degrading to EMPTY is enough on its own, no keyword needed.
    signature = ("EMPTY", "TEXT", "CURRENCY", "MONEY")
    sample_texts = ("", "xyz not a keyword", "R$", "12,00")
    assert classify_role(signature, BB_PRIMARY, sample_texts=sample_texts) == ROLE_SUMMARY


def test_keyword_alone_can_trigger_summary_role():
    primary = ("TEXT", "TEXT", "MONEY")
    signature = ("TEXT", "MONEY")  # different field count, no degradation match
    assert classify_role(signature, primary, sample_texts=("Grand Total", "10.00")) == ROLE_SUMMARY


def test_generic_non_banking_section_role():
    # A product-listing-shaped family: primary is (name, price, qty); a
    # category-divider row has just a label -- same structural rule as the
    # BB case, no Portuguese vocabulary involved.
    primary = ("TEXT", "INTEGER", "INTEGER")
    signature = ("TEXT", "EMPTY", "EMPTY")
    assert classify_role(signature, primary) == ROLE_SECTION


def test_unmatched_shape_falls_back_to_variant():
    primary = ("TEXT", "INTEGER", "INTEGER")
    signature = ("URL", "BOOLEAN")
    assert classify_role(signature, primary) == ROLE_VARIANT
