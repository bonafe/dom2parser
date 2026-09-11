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
from .fields import capture_value, field_text, relative_locator, scoped_element


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


@dataclass(frozen=True)
class CompiledRecord:
    """A record entry with its selector run and its locators compiled once.
    `anchors` bounds each record's span so a scope never reaches into the
    next record."""

    entry: object
    anchors: list
    locators: list  # (name, sibling, xpath or None for the scope itself, capture, attribute)

    @property
    def anchor_set(self) -> set:
        return set(self.anchors)


def compile_record(entry, root) -> CompiledRecord:
    return CompiledRecord(
        entry=entry,
        anchors=CSSSelector(entry.selector)(root),
        locators=[
            (f.name, f.sibling, relative_locator(f.locator) if f.locator else None, f.capture, f.attribute)
            for f in entry.fields
        ],
    )


def record_values(anchor, compiled: CompiledRecord, anchor_set: set | None = None) -> dict:
    anchor_set = compiled.anchor_set if anchor_set is None else anchor_set
    values = {}
    for name, sibling, xpath, capture, attribute in compiled.locators:
        scope = scoped_element(anchor, sibling, anchor_set)
        if scope is None:
            values[name] = ""
            continue
        if xpath is None:
            target = scope
        else:
            hits = xpath(scope)
            target = hits[0] if hits else None
        values[name] = capture_value(target, capture, attribute)
    if not compiled.locators:
        # A record with no discovered fields is still a record -- a tag
        # link, a bare list item -- and its own text is the value.
        values = {"_text": field_text(anchor)}
    return values


def _skip_reason(values: dict, skip_when: dict) -> str | None:
    if skip_when.get("all_empty") and not any(values.values()):
        return "all_empty"
    header = skip_when.get("header_values")
    if header and [values.get(k, "") for k in values] == list(header):
        return "header_row"
    return None


def extract_records(record_entry, root) -> list[Record]:
    compiled = compile_record(record_entry, root)
    anchor_set = compiled.anchor_set
    out = []
    for index, anchor in enumerate(compiled.anchors):
        values = record_values(anchor, compiled, anchor_set)
        reason = _skip_reason(values, record_entry.skip_when)
        out.append(Record(index=index, values=values, skipped=reason is not None, skip_reason=reason))
    return out


def execute(spec, html: str) -> dict:
    """Run every record type in `spec` against `html`, keyed by name."""
    root = parse_html(html)
    return {
        entry.name: Extraction(records=extract_records(entry, root)) for entry in spec.records
    }


__all__ = ["CompiledRecord", "Extraction", "Record", "compile_record", "execute", "extract_records", "record_values"]
