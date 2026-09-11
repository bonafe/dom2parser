"""Fase K: find the fields inside a record and a locator that reaches each
one in every record.

The compact representation flattens a record to `direct_children_text()`,
which throws away everything except the string: the child's tag, its
classes, and crucially its `href`/`src`. That is why link extraction is
impossible from the current output -- a `URL` in a signature only means
the visible *text* looked like a URL. Fields are therefore rediscovered
here, from the elements themselves.

Two rules keep this honest:

**Everything is derived and validated on the ORIGINAL tree.** Sanitization
deletes `script`/`style`/`svg`/`noscript` and comments, which shifts every
sibling position; a `:nth-of-type(3)` measured on the clean tree can point
at a different element in the document the parser will actually run
against. Working on the original throughout removes that whole class of
bug, at the price of having to skip the noise tags explicitly.

**A locator must hold across every record, not just the samples.** The
sample exists to keep the compact representation small; it is not a
licence to verify on a subset. A locator that resolves ambiguously in even
one record is rejected.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from cssselect import HTMLTranslator
from lxml.etree import XPath

from ..content.signature import classify
from ..fingerprint.hashattrs import semantic_class_tokens
from ..sanitize.strip import REMOVED_TAGS
from .naming import resolve_names, text_of

# `CSSSelector` compiles to `descendant-or-self::`, so a locator like
# `div` evaluated against a `div` record matches the record itself.
_TRANSLATOR = HTMLTranslator()

CAPTURE_ATTRS = {"a": "href", "img": "src", "time": "datetime", "meta": "content", "input": "value"}
MAX_FIELDS_PER_RECORD = 24
SKIP_TAGS = frozenset(REMOVED_TAGS) | {"template-ref", "br", "wbr"}


@dataclass(frozen=True)
class FieldSpec:
    name: str
    name_source: str
    locator: str
    type: str
    capture: str  # "text" | "attr"
    attribute: str | None
    present: int
    total: int

    @property
    def required(self) -> bool:
        return self.present == self.total


def _relative(css: str) -> XPath:
    return XPath(_TRANSLATOR.css_to_xpath(css, prefix="descendant::"))


def _is_text_leaf(el) -> bool:
    """True when the element's own text is not merely the concatenation of
    richer children -- i.e. it is where the value actually lives."""
    return not any(
        isinstance(child.tag, str) and child.tag not in SKIP_TAGS and text_of(child)
        for child in el
    )


def _capture_attr(el) -> str | None:
    attr = CAPTURE_ATTRS.get(el.tag if isinstance(el.tag, str) else "")
    return attr if attr and el.get(attr) else None


def _candidate_fields(record) -> list:
    out = []
    for el in record.iter():
        if not isinstance(el.tag, str) or el.tag in SKIP_TAGS or el is record:
            continue
        if _is_text_leaf(el) or _capture_attr(el):
            out.append(el)
    return out


def _own_segments(el) -> list[str]:
    tag = el.tag
    out = []
    for attr in ("itemprop", "data-testid"):
        value = el.get(attr)
        if value:
            out.append(f'{tag}[{attr}="{value}"]')
    out += [f"{tag}.{cls}" for cls in semantic_class_tokens(el.get("class", ""))]
    out.append(tag)
    return out


def _positional(el) -> str | None:
    parent = el.getparent()
    if parent is None:
        return None
    position = 1 + sum(
        1 for sib in parent.iterchildren(el.tag) if sib is not el and _precedes(sib, el)
    )
    return f"{el.tag}:nth-of-type({position})"


def _locator_candidates(el, record) -> list[str]:
    """Locators for one field, most stable first.

    Ancestor qualification is not optional polish: two `<a>` in different
    wrappers of the same record (dadosabertrosfiocruz.html: the CSV link
    and the data-dictionary link) are indistinguishable on their own, and
    `a:nth-of-type(1)` matches both because each is first *within its own
    parent*. Only the wrapper tells them apart."""
    own = _own_segments(el)
    out = list(own)

    ancestors = []
    node = el.getparent()
    while node is not None and node is not record:
        ancestors.append(node)
        node = node.getparent()
    for ancestor in ancestors:
        anchors = [s for s in _own_segments(ancestor) if s != ancestor.tag]
        for anchor in anchors:
            for segment in own:
                out.append(f"{anchor} {segment}")
                out.append(f"{anchor} > {segment}")

    positional = _positional(el)
    if positional:
        out.append(positional)
        for ancestor in ancestors:
            for anchor in [s for s in _own_segments(ancestor) if s != ancestor.tag]:
                out.append(f"{anchor} > {positional}")

    seen, unique = set(), []
    for candidate in out:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _precedes(a, b) -> bool:
    for node in a.getparent():
        if node is a:
            return True
        if node is b:
            return False
    return False


def _resolve(locator: str, records: list) -> list | None:
    """The element each record yields for this locator, or None if any
    record resolves it ambiguously. `None` entries mark absence, which is
    allowed -- that is what makes a field optional rather than invalid."""
    xpath = _relative(locator)
    resolved = []
    for record in records:
        try:
            hits = xpath(record)
        except Exception:
            return None
        if len(hits) > 1:
            return None
        resolved.append(hits[0] if hits else None)
    return resolved


def _value_of(el, attribute: str | None) -> str:
    if el is None:
        return ""
    return (el.get(attribute) or "") if attribute else text_of(el)


def _dominant_type(values: list[str]) -> str:
    present = [classify(v).type for v in values if v]
    return Counter(present).most_common(1)[0][0] if present else "EMPTY"


def _prune(columns: list[tuple]) -> list[tuple]:
    """Drop fields that carry no per-record information.

    A field whose text is identical in every record is furniture -- the
    `"Acessar o recurso"` on every download button. Three conditions all
    have to hold before it is dropped, and each excludes a real field:

    - present in EVERY record, so a sparse field that happens to have one
      value (a badge on 6 of 10 cards) is not mistaken for furniture;
    - no capture attribute, so a constant-labelled link keeps its href;
    - prose, so bancodobrasil.html's constant `R$` column survives on the
      strength of classifying as CURRENCY.
    """
    kept = []
    for column in columns:
        _, values, attribute, _ = column
        present = [v for v in values if v]
        if not present:
            continue
        furniture = (
            attribute is None
            and len(present) == len(values)
            and len(set(present)) == 1
            and _dominant_type(values) in ("TEXT", "EMPTY")
        )
        if not furniture:
            kept.append(column)
    return kept


def discover(records: list) -> list[FieldSpec]:
    """Fields shared by every record in `records`, which must be elements
    of the original document."""
    if not records:
        return []

    seen_signatures = set()
    columns: list[tuple] = []
    for el in _candidate_fields(records[0]):
        attribute = _capture_attr(el)
        locator, resolved = None, None
        for candidate in _locator_candidates(el, records[0]):
            resolved = _resolve(candidate, records)
            if resolved is not None and resolved[0] is el:
                locator = candidate
                break
        if locator is None:
            continue

        signature = tuple(id(r) if r is not None else None for r in resolved)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        values = [_value_of(r, attribute) for r in resolved]
        columns.append((locator, values, attribute, resolved))

    columns = _prune(columns)[:MAX_FIELDS_PER_RECORD]
    if not columns:
        return []

    rows = [[column[1][i] for column in columns] for i in range(len(records))]
    types = [_dominant_type(column[1]) for column in columns]
    first_elements = [column[3][0] for column in columns]
    names = resolve_names(first_elements, rows, types)

    return [
        FieldSpec(
            name=name,
            name_source=source,
            locator=locator,
            type=field_type,
            capture="attr" if attribute else "text",
            attribute=attribute,
            present=sum(1 for v in values if v),
            total=len(records),
        )
        for (name, source), (locator, values, attribute, _), field_type in zip(
            names, columns, types
        )
    ]


__all__ = ["FieldSpec", "discover"]
