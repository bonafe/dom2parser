"""Fase N: locate a single value -- a due date, a total, the name on a card --
from one example of it, and emit a locator that finds the same field on the
next page, where the value is different.

Records (Fase J/K) are found by repetition: the page itself shows which
elements belong together. A lone field has no such signal, so its target
comes from outside: the caller already knows one value ("28/10/2026", from
a person or an LLM reading the page) and asks where it lives. That makes
this the same kind of search as `selector.synthesize`: the element is known,
candidates are generated liberally, and only a candidate that was *run*
against the document and reproduced the value ships.

Reproducing the value on the sample is necessary, not sufficient. A locator
that finds "28/10/2026" by its own text would pass here and fail on every
other page. Two rules keep the locator about the field and not the value:

- **The value never appears in the locator.** Candidates are built from what
  surrounds the value -- the label next to it ("Vencimento"), the element's
  class, its id, its position -- never from the value's text.
- **When the value shares its element with other text, it is cut out by
  shape, not by content.** "Vencimento 28/10/2026" yields the pattern
  `Vencimento\\s*(\\d{1,2}/\\d{1,2}(?:/\\d{2,4})?)`: the label stays literal,
  the value becomes the shape of a date, so next month's date matches too.

A value that also occurs inside a repeated record -- the previous balance
that happens to equal one purchase -- is taken from the smallest place it
occurs: outside every record first, then the record with the fewest rows.
What a long list says is data and changes every month; anchoring a lone
field on "MERCADO UM" reproduces the sample and breaks on the next
statement. A two-row summary table (balance, total) is a record too, but
short ones hold labelled values, long ones hold data.

Candidates are ranked by how likely they are to survive a page that changed
a little. A label is what a page keeps stable for its readers, so it comes
first; a class is next; an absolute path, which breaks when anything above
the field moves, is the last resort and is reported as such (`strategy`).

The locator is XPath, unlike the CSS of records: anchoring on a label's text
needs `normalize-space(.)` comparisons, which CSS cannot express.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml.etree import XPath, XPathError

from ..content.signature import classify
from ..dom_utils import collapse_whitespace
from ..fingerprint.hashattrs import semantic_class_tokens
from ..html_io import parse_html
from .fields import SKIP_TAGS, field_text
from .spec import ScalarEntry

MAX_LABEL_CHARS = 80
# How many element siblings back a label may sit: "Cartão", then the card
# name, then the card number puts the number two hops from its label.
MAX_LABEL_HOPS = 3

# `normalize-space` only folds ASCII whitespace; pages pad labels with nbsp.
_NORM = "normalize-space(translate({0}, ' ', ' '))"
_DATE_RE = r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"
_NUMBER_RE = r"[-+]?\d[\d.,]*"
_LETTERS = re.compile(r"[^\W\d_]{2}")
_GENERATED_ID = re.compile(r"\d{4,}|[0-9a-f]{8,}", re.IGNORECASE)

# Lower ranks survive layout changes better.
STRATEGY_RANK = {"label": 0, "prefix": 1, "class": 2, "id": 3, "class-indexed": 4, "position": 5}


@dataclass(frozen=True)
class ScalarSynthesis:
    """A usable entry, or the reason there is none -- never a guess."""

    entry: ScalarEntry | None
    reason: str | None = None
    tried: int = 0

    @property
    def ok(self) -> bool:
        return self.entry is not None


def _literal(text: str) -> str:
    """`text` as an XPath string literal, whatever quotes it contains."""
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


def _text(el) -> str:
    return collapse_whitespace(field_text(el))


def _is_label(text: str, value: str) -> bool:
    return (
        0 < len(text) <= MAX_LABEL_CHARS
        and value not in text
        and _LETTERS.search(text) is not None
    )


def _value_regex(value: str) -> str | None:
    """The shape a value of this kind takes, or None for free text."""
    if re.fullmatch(_DATE_RE, value):
        return _DATE_RE
    if re.fullmatch(r"[-+]?\s*[\d.,]*\d", value):
        return _NUMBER_RE
    return None


def value_pattern(text: str, value: str) -> str | None:
    """The regex that cuts `value` out of `text` by shape, or None when the
    element holds the value alone. Raises ValueError when no pattern can
    say where the value is without naming it.

    Only the label-like tail before the value stays literal: digits before
    it belong to other values on this page and will differ on the next.
    """
    if text == value:
        return None
    start = text.find(value)
    if start < 0:
        raise ValueError("value not in text")
    before, after = text[:start], text[start + len(value):]
    prefix = re.split(r"\d", before)[-1].strip()
    shape = _value_regex(value)
    if shape is not None:
        head = re.escape(prefix) + r"\s*" if prefix else ""
        return f"{head}({shape})"
    # Free text has no shape, so both ends must be pinned by something that
    # is not the value: the label before it, and what follows or the end.
    suffix = re.split(r"\d", after)[0].strip()
    head = re.escape(prefix) + r"\s*" if prefix else r"^\s*"
    tail = r"\s*" + re.escape(suffix) if suffix else r"\s*$"
    return f"{head}(.+?){tail}"


def _targets(root, value: str) -> list:
    """The innermost elements whose text contains the value."""
    holding = []
    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag in SKIP_TAGS:
            continue
        if value in collapse_whitespace(el.text_content()) and value in _text(el):
            holding.append(el)
    holding_set = set(holding)
    return [el for el in holding if not any(child in holding_set for child in el)]


def _label_candidates(el, value: str) -> list[tuple[str, str, str]]:
    """`<td>Total</td><td>13,40</td>`, `<dt>` + `<dd>`, a label `span`
    followed by value `span`s: the nearest label-like preceding sibling,
    then the n-th element of the target's tag after it.

    A sibling with the target's own tag and class is a peer -- the card's
    name next to the card's number -- and a peer is a value, not a label:
    anchoring on it works on this page and breaks on the next card."""
    hops, sibling = 0, el.getprevious()
    while sibling is not None and hops < MAX_LABEL_HOPS:
        if isinstance(sibling.tag, str) and sibling.tag not in SKIP_TAGS:
            hops += 1
            text = _text(sibling)
            peer = sibling.tag == el.tag and bool(el.get("class")) and sibling.get("class") == el.get("class")
            if not peer and _is_label(text, value):
                between = 1
                node = sibling.getnext()
                while node is not el:
                    if node.tag == el.tag:
                        between += 1
                    node = node.getnext()
                locator = (
                    f"//{sibling.tag}[{_NORM.format('.')}={_literal(text)}]"
                    f"/following-sibling::{el.tag}[{between}]"
                )
                return [("label", locator, text)]
        sibling = sibling.getprevious()
    return []


def _prefix_candidate(el, pattern: str | None, text: str, value: str) -> list[tuple[str, str, str]]:
    """The label shares the element with the value ("Vencimento 28/10/2026"):
    the innermost element of that tag whose text starts with the label."""
    if not pattern:
        return []
    prefix = re.split(r"\d", text[: text.find(value)])[-1].strip()
    if not _is_label(prefix, value):
        return []
    starts = f"starts-with({_NORM.format('.')}, {_literal(prefix)})"
    return [("prefix", f"//{el.tag}[{starts}][not(.//{el.tag}[{starts}])]", prefix)]


def _class_candidates(el, root) -> list[tuple[str, str, str | None]]:
    out = []
    for token in semantic_class_tokens(el.get("class") or ""):
        locator = f"//{el.tag}[contains(concat(' ', normalize-space(@class), ' '), ' {token} ')]"
        matches = XPath(locator)(root)
        if el not in matches:
            continue
        index = matches.index(el) + 1
        if index == 1:
            out.append(("class", locator, None))
        else:
            out.append(("class-indexed", f"({locator})[{index}]", None))
    return out


def _candidates(el, root, pattern, text, value) -> list[tuple[str, str, str | None]]:
    out = _label_candidates(el, value) + _prefix_candidate(el, pattern, text, value)
    out += _class_candidates(el, root)
    element_id = el.get("id")
    if element_id and not _GENERATED_ID.search(element_id):
        out.append(("id", f"//*[@id={_literal(element_id)}]", None))
    out.append(("position", el.getroottree().getpath(el), None))
    return out


def extract_scalar(entry: ScalarEntry, root) -> str:
    """Run one entry against a parsed document. Empty string when the
    locator finds nothing or the pattern does not match -- the caller
    decides whether an empty field is a failure."""
    try:
        hits = XPath(entry.locator)(root)
    except XPathError:
        return ""
    if not hits:
        return ""
    target = hits[0]
    raw = (target.get(entry.attribute) or "") if entry.capture == "attr" else _text(target)
    if entry.pattern is None:
        return raw
    match = re.search(entry.pattern, raw)
    return match.group(1).strip() if match else ""


def record_elements(root, records) -> dict:
    """Each element inside a repeated record of `records` (RecordEntry list),
    including the extra siblings of a multi-element record, mapped to the
    number of rows of the smallest record it belongs to."""
    from lxml.cssselect import CSSSelector

    sizes: dict = {}
    for record in records:
        try:
            anchors = CSSSelector(record.selector)(root)
        except Exception:
            continue
        for anchor in anchors:
            node = anchor
            for _ in range(max(1, record.span)):
                if node is None:
                    break
                for el in node.iter():
                    sizes[el] = min(sizes.get(el, len(anchors)), len(anchors))
                node = node.getnext()
    return sizes


def _verified_records(html: str) -> list:
    from .build import build_spec

    return [r for r in build_spec(html).records
            if r.verified.get("precision", 0) >= 1.0 and r.verified.get("recall", 0) >= 1.0]


def synthesize_scalar(root, name: str, example: str, record_sizes: dict | None = None) -> ScalarSynthesis:
    """Find where `example` lives in `root` and a locator that reproduces it
    without naming it. `root` is the ORIGINAL document, parsed; occurrences
    inside long records (`record_elements`) lose to the rest."""
    record_sizes = record_sizes or {}
    value = collapse_whitespace(example)
    if not value:
        return ScalarSynthesis(entry=None, reason="empty example")
    targets = _targets(root, value)
    if not targets:
        return ScalarSynthesis(entry=None, reason="example not found in the document")

    tried, best = 0, None
    for el in targets:
        text = _text(el)
        try:
            pattern = value_pattern(text, value)
        except ValueError:
            continue
        for strategy, locator, label in _candidates(el, root, pattern, text, value):
            if len(value) >= 4 and value in locator:
                continue
            tried += 1
            try:
                matched = len(XPath(locator)(root))
            except XPathError:
                continue
            entry = ScalarEntry(
                name=name, locator=locator, capture="text", attribute=None, pattern=pattern,
                type=classify(value).type, strategy=strategy, label=label,
                verified={"reproduced": True, "matched": matched},
            )
            if extract_scalar(entry, root) != value:
                continue
            key = (record_sizes.get(el, 0), STRATEGY_RANK[strategy], matched != 1, len(locator))
            if best is None or key < best[0]:
                best = (key, entry)
    if best is None:
        return ScalarSynthesis(entry=None, reason="no candidate reproduced the example", tried=tried)
    return ScalarSynthesis(entry=best[1], tried=tried)


def synthesize_scalars(html: str, examples: dict[str, str], records=None) -> tuple[list[ScalarEntry], list[dict]]:
    """One entry per example that could be located; a failure, with its
    reason, for each that could not. `records` are the page's repeated
    records (RecordEntry); by default the verified ones `build_spec` finds."""
    root = parse_html(html)
    inside = record_elements(root, _verified_records(html) if records is None else records)
    entries, failures = [], []
    for name, example in examples.items():
        result = synthesize_scalar(root, name, example, inside)
        if result.ok:
            entries.append(result.entry)
        else:
            failures.append({"name": name, "reason": result.reason, "tried": result.tried})
    return entries, failures


def execute_scalars(entries, html: str) -> dict[str, str]:
    root = parse_html(html)
    return {entry.name: extract_scalar(entry, root) for entry in entries}


__all__ = [
    "STRATEGY_RANK",
    "ScalarEntry",
    "ScalarSynthesis",
    "execute_scalars",
    "extract_scalar",
    "record_elements",
    "synthesize_scalar",
    "synthesize_scalars",
    "value_pattern",
]
