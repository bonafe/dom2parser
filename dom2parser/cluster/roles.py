"""Fase E (new): label a non-dominant content-signature variant within a
family of same-shape clusters (see `cluster.families`) with a small,
generic role, so an LLM consuming the compact representation knows *why*
a row with a different signature sits alongside the family's main record
type -- e.g. Banco do Brasil's `tr > td > div.lancamentos > table > tbody
> tr` has 122 `DATE | TEXT | CURRENCY | MONEY` transaction rows, but also
12 `EMPTY | TEXT | EMPTY | EMPTY` category-header rows and 3
`EMPTY | TEXT | CURRENCY | MONEY` subtotal/total rows sharing the exact
same DOM shape.

Deliberately structural-first: the primary rule for each role is a
field-count/field-type comparison against the family's primary signature,
which holds regardless of the page's language or domain. A small
cross-locale keyword list is used only as a secondary, non-load-bearing
signal for `summary` (same register as `CONTENT_KEYWORD_RE` in
`cluster/rank.py`) -- never the sole trigger, since a closed keyword list
can never be exhaustive across languages.
"""

from __future__ import annotations

import re

ROLE_PRIMARY = "primary"
ROLE_EMPTY = "empty"
ROLE_SECTION = "section"
ROLE_SUMMARY = "summary"
ROLE_VARIANT = "variant"

SUMMARY_KEYWORDS_SOURCE = (
    "total", "subtotal", "sum", "balance", "saldo", "resumo", "resultado",
    "grand total", "amount due", "sub-total",
)
SUMMARY_KEYWORD_RE = re.compile(
    "|".join(re.escape(k) for k in SUMMARY_KEYWORDS_SOURCE), re.IGNORECASE
)


def _populated_count(signature: tuple[str, ...]) -> int:
    return sum(1 for t in signature if t != "EMPTY")


def _degraded_to_empty_positions(signature: tuple[str, ...], primary_signature: tuple[str, ...]) -> int:
    """How many positions went from a populated type in `primary_signature`
    to EMPTY in `signature`, when the two are the same length."""
    if len(signature) != len(primary_signature):
        return 0
    return sum(1 for a, b in zip(primary_signature, signature) if b == "EMPTY" and a != "EMPTY")


def classify_role(
    signature: tuple[str, ...],
    primary_signature: tuple[str, ...],
    sample_texts: tuple[str, ...] | None = None,
) -> str:
    """Classify a non-primary content signature relative to its family's
    primary (dominant) signature. Only ever called for the non-primary
    members of a family -- the primary itself is always `ROLE_PRIMARY`,
    decided by the caller (`cluster.families.build_families`), not here."""
    if not signature or all(t == "EMPTY" for t in signature):
        return ROLE_EMPTY

    populated = _populated_count(signature)
    primary_populated = _populated_count(primary_signature)

    if populated < primary_populated and populated == 1 and "TEXT" in signature:
        return ROLE_SECTION

    same_or_one_fewer_fields = len(signature) == len(primary_signature)
    degraded = _degraded_to_empty_positions(signature, primary_signature)
    if same_or_one_fewer_fields and degraded >= 1:
        return ROLE_SUMMARY

    if sample_texts and any(SUMMARY_KEYWORD_RE.search(t) for t in sample_texts if t):
        return ROLE_SUMMARY

    return ROLE_VARIANT


__all__ = [
    "ROLE_PRIMARY",
    "ROLE_EMPTY",
    "ROLE_SECTION",
    "ROLE_SUMMARY",
    "ROLE_VARIANT",
    "classify_role",
]
