"""Fase D: classify a text node's content into a semantic type -- always
from the text itself, never from the element's class (see hashattrs'
sibling module docstring for the CKAN case that makes this a hard
requirement: the same class backs both FILE_FORMAT and COUNT_LABELED
values). Falls back to TEXT (or EMPTY) whenever nothing more specific
matches, so unexpected/malformed content (e.g. an error string sitting in
what's usually a date field) degrades gracefully instead of forcing a
wrong type or raising.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import classifiers as c


@dataclass(frozen=True)
class Signature:
    type: str
    raw: str
    value: object = None


# Ordered most-specific-first; the first match wins.
_RULES = [
    ("DATETIME", c.match_datetime),
    ("DATE", c.match_date),
    ("TIME", c.match_time),
    ("EMAIL", c.match_email),
    ("URL", c.match_url),
    ("PHONE", c.match_phone),
    ("PERCENTAGE", c.match_percentage),
    ("MONEY", c.match_money),
    # INTEGER before DECIMAL: a lone '.'/',' with 3 trailing digits is
    # ambiguous between a BR-style thousands separator ("1.234" = 1234)
    # and a US-style decimal ("1.234" = one and a fraction). We resolve it
    # in favor of INTEGER (matches this project's BR-locale examples);
    # MONEY (checked above, requires exactly 2 fractional digits) already
    # claims the currency-amount case this would otherwise collide with.
    ("INTEGER", c.match_integer),
    ("CURRENCY", c.match_currency),
    ("FILE_FORMAT", c.match_file_format),
    ("COUNT_LABELED", c.match_count_labeled),
    ("BOOLEAN", c.match_boolean),
    ("DECIMAL", c.match_decimal),
]


def classify(text: str | None) -> Signature:
    raw = text or ""
    normalized = c.normalize(raw)
    if c.is_empty(normalized):
        return Signature(type="EMPTY", raw=raw)

    for type_name, matcher in _RULES:
        try:
            value = matcher(normalized)
        except Exception:
            continue
        if value is not None and value is not False:
            return Signature(type=type_name, raw=raw, value=value)
        if value is False:
            # BOOLEAN's False is a legitimate match, not "no match".
            return Signature(type=type_name, raw=raw, value=value)

    return Signature(type="TEXT", raw=raw)
