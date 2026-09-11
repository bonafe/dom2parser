"""Fase M: measure what a parser actually returned.

The report shape comes straight from the spec's "Validação do parser":

    registros encontrados: 123
    com data: 122
    com descrição: 123
    com moeda: 121
    com valor: 119

Fill rate alone is not enough, so type conformance is measured too, by
reusing `content.signature.classify` -- the very classifier that decided
the field's declared type during synthesis. A field declared `MONEY` whose
values stop classifying as `MONEY` is a locator that has drifted onto the
wrong element, which is exactly the failure a fill-rate-only check misses.

`failures` collects a bounded sample of records where a required field
came back empty. That is deliberately the payload the spec's repair loop
asks for: the library supplies the evidence, and whoever wants to repair
the parser decides how.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..content.signature import classify

MAX_FAILURE_SAMPLES = 5


@dataclass
class FieldMetrics:
    name: str
    declared_type: str
    present: int
    conforming: int
    total: int


@dataclass
class ValidationReport:
    record_name: str
    found: int
    skipped: int
    fields: list[FieldMetrics] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.found > 0 and not self.failures

    def as_text(self) -> str:
        lines = [f"registros encontrados: {self.found}"]
        for metrics in self.fields:
            lines.append(f"com {metrics.name}: {metrics.present}")
        return "\n".join(lines)


def validate(record_entry, extraction) -> ValidationReport:
    kept = extraction.kept
    metrics = []
    for entry in record_entry.fields:
        values = [record.values.get(entry.name, "") for record in kept]
        present = [v for v in values if v]
        metrics.append(
            FieldMetrics(
                name=entry.name,
                declared_type=entry.type,
                present=len(present),
                conforming=sum(1 for v in present if classify(v).type == entry.type),
                total=len(kept),
            )
        )

    required = [entry.name for entry in record_entry.fields if entry.required]
    failures = []
    for record in kept:
        missing = [name for name in required if not record.values.get(name)]
        if missing and len(failures) < MAX_FAILURE_SAMPLES:
            failures.append({"index": record.index, "missing": missing, "values": record.values})

    return ValidationReport(
        record_name=record_entry.name,
        found=len(kept),
        skipped=len(extraction.records) - len(kept),
        fields=metrics,
        failures=failures,
    )


__all__ = ["FieldMetrics", "ValidationReport", "validate"]
