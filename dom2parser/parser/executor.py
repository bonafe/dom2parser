"""Fase M: run a `ParserSpec` against the ORIGINAL document.

The spec's load-bearing invariant is that the generated parser runs on the
full original HTML, never on the compact representation -- the compact
form exists to decide *what* to extract, not to be extracted from. So this
takes raw HTML, not anything the pipeline produced.

Skipped rows are returned, not dropped. A header row that the synthesizer
recognised is still a row of the document, and a consumer that silently
receives 153 of 154 rows has no way to tell a deliberate skip from a
broken locator. Every record carries `skipped` and the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml.cssselect import CSSSelector

from ..html_io import parse_html
from .fields import _value_of, relative_locator
from .naming import text_of


@dataclass
class Record:
    index: int
    values: dict
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class Extraction:
    records: list[Record] = field(default_factory=list)

    @property
    def kept(self) -> list[Record]:
        return [r for r in self.records if not r.skipped]


def _skip_reason(values: dict, skip_when: dict) -> str | None:
    if skip_when.get("all_empty") and not any(values.values()):
        return "all_empty"
    header = skip_when.get("header_values")
    if header and [values.get(k, "") for k in values] == list(header):
        return "header_row"
    return None


def extract_records(record_entry, root) -> list[Record]:
    elements = CSSSelector(record_entry.selector)(root)
    locators = {f.name: (relative_locator(f.locator), f.attribute) for f in record_entry.fields}

    out = []
    for index, element in enumerate(elements):
        values = {}
        for name, (xpath, attribute) in locators.items():
            hits = xpath(element)
            values[name] = _value_of(hits[0], attribute) if hits else ""
        if not locators:
            # A record with no discovered fields is still a record -- a
            # glossary <dd>, a tag link -- and its own text is the value.
            values = {"_text": text_of(element)}
        reason = _skip_reason(values, record_entry.skip_when)
        out.append(Record(index=index, values=values, skipped=reason is not None, skip_reason=reason))
    return out


def execute(spec, html: str) -> dict:
    """Run every record type in `spec` against `html`, keyed by name."""
    root = parse_html(html)
    return {
        entry.name: Extraction(records=extract_records(entry, root)) for entry in spec.records
    }


__all__ = ["Record", "Extraction", "execute", "extract_records"]
