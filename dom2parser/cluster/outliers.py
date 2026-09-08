"""Fase G (part 2): find outlier elements *within* an already-homogeneous
cluster -- one that Fase E has already narrowed down to a single DOM
fingerprint AND a single content-signature sequence (so the classic
"special row" / "different kind of record" case, like bancodobrasil.html's
`SALDO FATURA ANTERIOR` line, is already its own separate Cluster by the
time this module runs; that's Fase E's job, not this one).

What's left to flag here is intra-cluster variation worth showing the LLM
a sample of: the min/max of any numeric-shaped field (e.g. the largest and
smallest transaction MONEY value), and the shortest/longest overall text
record (an unusually terse or unusually verbose instance).
"""

from __future__ import annotations

import re

from ..content.signature import classify
from ..dom_utils import direct_children_text, full_text
from .siblings import Cluster

NUMERIC_SIGNATURE_TYPES = {"MONEY", "INTEGER", "DECIMAL", "PERCENTAGE", "COUNT_LABELED"}

_BR_DECIMAL_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d+$")
_PLAIN_DECIMAL_RE = re.compile(r"^-?\d+,\d+$")
_US_DECIMAL_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d+$")
_PLAIN_INT_RE = re.compile(r"^-?\d+(?:\.\d+)?%?$")


def _to_number(text: str, sig_type: str) -> float | None:
    if sig_type == "COUNT_LABELED":
        sig = classify(text)
        return float(sig.value[0]) if sig.value else None

    t = (text or "").strip().rstrip("%")
    try:
        if _BR_DECIMAL_RE.match(t):
            return float(t.replace(".", "").replace(",", "."))
        if _PLAIN_DECIMAL_RE.match(t):
            return float(t.replace(",", "."))
        if _US_DECIMAL_RE.match(t):
            return float(t.replace(",", ""))
        if _PLAIN_INT_RE.match(t):
            return float(t)
    except ValueError:
        return None
    return None


def numeric_field_outlier_indices(cluster: Cluster) -> set[int]:
    """Indices (within cluster.elements) of the element(s) holding the
    min/max value of each numeric-typed field position."""
    outliers: set[int] = set()
    for field_index, sig_type in enumerate(cluster.content_signature):
        if sig_type not in NUMERIC_SIGNATURE_TYPES:
            continue
        parsed: list[tuple[float, int]] = []
        for i, el in enumerate(cluster.elements):
            children_text = direct_children_text(el)
            if field_index >= len(children_text):
                continue
            num = _to_number(children_text[field_index], sig_type)
            if num is not None:
                parsed.append((num, i))
        if not parsed:
            continue
        parsed.sort()
        outliers.add(parsed[0][1])
        outliers.add(parsed[-1][1])
    return outliers


def text_length_outlier_indices(cluster: Cluster) -> set[int]:
    """Indices of the shortest and longest overall records by text length."""
    lengths = []
    for i, el in enumerate(cluster.elements):
        lengths.append((len(full_text(el)), i))
    if not lengths:
        return set()
    lengths.sort()
    return {lengths[0][1], lengths[-1][1]}
