"""Fase L: the serialized parser.

What the pipeline emits is **data**, not code: a record selector, a field
list, and the measurements that justified them. It is executed by
`parser.executor` through lxml and never passes through `exec()`.

That choice is what makes the rest of the design possible. A parser that
is data can be validated field by field, diffed when it changes, edited by
hand where a derived name reads badly, and repaired by replacing one
locator instead of regenerating a file. It also means nothing a page
contains can ever become something this library runs.

`verified` is not decoration. It records what was measured at synthesis
time -- how many elements the selector matched and how completely it
covered the known records -- so a consumer can tell a selector that was
proven exact from one that was merely the best available.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import yaml

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FieldEntry:
    name: str
    locator: str  # CSS relative to the scoped element; "" means the scoped element itself
    type: str
    capture: str  # "text" | "attr"
    attribute: str | None
    required: bool
    present: int
    total: int
    name_source: str
    # Which element of the record the locator is relative to: 0 is the
    # anchor the selector matched, 1 its next element sibling, and so on.
    # Only ever non-zero when the record's `span` is greater than one.
    sibling: int = 0


@dataclass(frozen=True)
class RecordEntry:
    name: str
    selector: str
    count: int
    fields: list[FieldEntry]
    skip_when: dict = field(default_factory=dict)
    verified: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    # How many consecutive element siblings make up one record. A Hacker
    # News item is three `tr` (title row, subtext row, spacer); a glossary
    # entry is `dt` + `dd`. The selector matches the first of them.
    span: int = 1


@dataclass(frozen=True)
class ParserSpec:
    schema_version: int
    records: list[RecordEntry]
    failures: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "records": [asdict(r) for r in self.records],
            "failures": list(self.failures),
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "ParserSpec":
        records = [
            RecordEntry(
                name=r["name"],
                selector=r["selector"],
                count=r["count"],
                fields=[FieldEntry(**f) for f in r["fields"]],
                skip_when=r.get("skip_when", {}),
                verified=r.get("verified", {}),
                provenance=r.get("provenance", {}),
                span=r.get("span", 1),
            )
            for r in data.get("records", [])
        ]
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            records=records,
            failures=data.get("failures", []),
        )

    @classmethod
    def from_yaml(cls, text: str) -> "ParserSpec":
        return cls.from_dict(yaml.safe_load(text))

    @classmethod
    def from_json(cls, text: str) -> "ParserSpec":
        return cls.from_dict(json.loads(text))


__all__ = ["SCHEMA_VERSION", "FieldEntry", "RecordEntry", "ParserSpec"]
