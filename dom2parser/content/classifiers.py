"""Individual pattern classifiers for content_signature. Each returns a
parsed value (or True/None) on match; signature.py tries them in order of
specificity and degrades to TEXT/EMPTY when nothing matches -- classifiers
must never raise on unexpected input, only fail to match.
"""

from __future__ import annotations

import re

DATE_RE = re.compile(
    r"^\s*\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\s*$"  # 18/07 (year implicit) or 18/07/2026
    r"|^\s*\d{4}-\d{1,2}-\d{1,2}\s*$"  # ISO 2026-07-18
)
TIME_RE = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)(:[0-5]\d)?\s*$")
DATETIME_SEP_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s*$")

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)

PHONE_RE = re.compile(r"^\(?\d{2,3}\)?[\s.-]?\d{4,5}-?\d{4}$")

PERCENTAGE_RE = re.compile(r"^-?\d{1,3}(?:[.,]\d+)?\s?%$")

# Brazilian-style decimal: thousands separator '.', decimal separator ','.
MONEY_BR_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")
# US-style decimal with exactly 2 fractional digits, e.g. 52.74
MONEY_US_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}$")

DECIMAL_RE = re.compile(r"^-?\d+[.,]\d+$")
INTEGER_RE = re.compile(r"^-?\d{1,3}(?:[.,]\d{3})*$|^-?\d+$")

CURRENCY_TOKENS = {"r$", "us$", "$", "€", "eur", "usd", "brl", "gbp", "£", "¥"}

FILE_FORMAT_TOKENS = {
    "csv", "pdf", "json", "xml", "xls", "xlsx", "ods", "odt", "doc", "docx",
    "ppt", "pptx", "zip", "kml", "kmz", "html", "htm", "txt", "png", "jpg",
    "jpeg", "gif", "svg", "shp", "geojson", "rdf", "wms", "wfs", "api",
}

COUNT_LABELED_RE = re.compile(r"^(\d[\d.,]*)\s+(\S.*)$")

BOOLEAN_TOKENS = {
    "true": True, "false": False,
    "sim": True, "não": False, "nao": False,
    "yes": True, "no": False,
}


def normalize(text: str) -> str:
    return (text or "").strip()


def is_empty(text: str) -> bool:
    return normalize(text) == ""


def match_date(text: str) -> str | None:
    return text if DATE_RE.match(text) else None


def match_time(text: str) -> str | None:
    return text if TIME_RE.match(text) else None


def match_datetime(text: str) -> tuple[str, str] | None:
    m = DATETIME_SEP_RE.match(text)
    if not m:
        return None
    left, right = m.group(1), m.group(2)
    if match_date(left) and match_time(right):
        return (left, right)
    return None


def match_email(text: str) -> str | None:
    return text if EMAIL_RE.match(text) else None


def match_url(text: str) -> str | None:
    return text if URL_RE.match(text) else None


def match_phone(text: str) -> str | None:
    return text if PHONE_RE.match(text) else None


def match_percentage(text: str) -> str | None:
    return text if PERCENTAGE_RE.match(text) else None


def match_money(text: str) -> str | None:
    if MONEY_BR_RE.match(text) or MONEY_US_RE.match(text):
        return text
    return None


def match_currency(text: str) -> str | None:
    return text if normalize(text).lower() in CURRENCY_TOKENS else None


def match_decimal(text: str) -> str | None:
    return text if DECIMAL_RE.match(text) else None


def match_integer(text: str) -> str | None:
    return text if INTEGER_RE.match(text) else None


def match_file_format(text: str) -> str | None:
    stripped = normalize(text).lstrip(".").lower()
    return stripped if stripped in FILE_FORMAT_TOKENS else None


def match_count_labeled(text: str) -> tuple[int, str] | None:
    m = COUNT_LABELED_RE.match(normalize(text))
    if not m:
        return None
    digits = m.group(1).replace(".", "").replace(",", "")
    if not digits.isdigit():
        return None
    return (int(digits), m.group(2).strip())


def match_boolean(text: str) -> bool | None:
    key = normalize(text).lower()
    return BOOLEAN_TOKENS.get(key)
