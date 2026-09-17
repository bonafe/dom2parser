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

import re
from collections import Counter
from dataclasses import dataclass

from cssselect import HTMLTranslator
from lxml.etree import XPath

from ..content.signature import classify
from ..dom_utils import collapse_whitespace
from ..fingerprint.hashattrs import semantic_class_tokens
from ..sanitize.strip import REMOVED_TAGS
from .naming import resolve_names, slugify, table_header_cells, text_of

_DECORATION_RE = re.compile(r"^[^\w\s]$")


# `CSSSelector` compiles to `descendant-or-self::`, so a locator like
# `div` evaluated against a `div` record matches the record itself.
_TRANSLATOR = HTMLTranslator()

CAPTURE_ATTRS = {"a": "href", "img": "src", "time": "datetime", "meta": "content", "input": "value"}
MAX_FIELDS_PER_RECORD = 24
MIN_FIELD_PRESENCE = 2
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
    sibling: int = 0

    @property
    def required(self) -> bool:
        return self.present == self.total


def relative_locator(css: str) -> XPath:
    """Compile a locator relative to the element it is evaluated against.

    A leading `>` (the relative-selector form of Selectors 4) means a
    direct child. It matters: `p:nth-of-type(1)` alone compiles to
    `descendant::p[...]` and also finds the first paragraph of every note
    box nested inside a glossary definition, which made the definition's
    own first paragraph ambiguous and lost it."""
    if css.startswith(">"):
        return XPath(_TRANSLATOR.css_to_xpath(css[1:].strip(), prefix="child::"))
    return XPath(_TRANSLATOR.css_to_xpath(css, prefix="descendant::"))


def is_decoration(child) -> bool:
    """A child whose entire text is one symbol -- the `¶` of a permalink,
    a `›` chevron, a `#` anchor -- is furniture hanging off the value, not
    part of it. Without this every Sphinx `<dt>` reads as a non-leaf and
    the term itself is never a candidate."""
    return bool(_DECORATION_RE.match(text_of(child)))


# HTML's own phrasing content: a child of one of these tags is part of the
# sentence it sits in, not a nested container. A `<p>` holding two links
# and a `<code>` is still one value -- the paragraph -- which is what
# keeps a glossary definition from dissolving into its hyperlinks.
INLINE_TAGS = frozenset(
    {
        "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "i", "kbd",
        "mark", "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var",
    }
)


def _own_text(el) -> str:
    return collapse_whitespace((el.text or "") + "".join(child.tail or "" for child in el))


def _is_text_leaf(el) -> bool:
    """True when the element is where a value lives, rather than a box
    holding several.

    A block child with text always makes a container. An inline child is
    part of the sentence only when the element has prose of its own that
    outweighs its inline children -- a glossary definition with two links
    in it is one value. When the inline children carry the text and the
    element itself has little or none, they are labelled pieces, not
    prose: Hacker News's `td.title` holds `span.titleline` and
    `span.sitebit`, and the quotes site's `span` holds `by`, then
    `small.author`, then a link -- three values, not one."""
    inline_text = 0
    for child in el:
        if not isinstance(child.tag, str) or child.tag in SKIP_TAGS or is_decoration(child):
            continue
        text = text_of(child)
        if not text:
            continue
        if child.tag not in INLINE_TAGS:
            return False
        inline_text += len(text)
    return inline_text == 0 or len(_own_text(el)) > inline_text


def _inside_leaf(el, scope) -> bool:
    """True when some ancestor below `scope` is itself a text leaf, so this
    element's text is already part of a value and only an attribute of it
    (a link's href) can add anything."""
    node = el.getparent()
    while node is not None and node is not scope:
        if _is_text_leaf(node) and field_text(node):
            return True
        node = node.getparent()
    return False


def field_text(el) -> str:
    """The element's text with decoration children left out."""
    parts = [el.text or ""]
    for child in el:
        if isinstance(child.tag, str) and child.tag not in SKIP_TAGS and not is_decoration(child):
            parts.append(text_of(child))
        parts.append(child.tail or "")
    return collapse_whitespace("".join(parts))


def scoped_element(anchor, sibling: int, anchors: set | None = None):
    """The element a field with `sibling=j` is relative to: the anchor
    itself for 0, else its j-th following element sibling -- but never
    past the next record's anchor, so a term with no definition of its own
    does not borrow the next term as one."""
    node = anchor
    for _ in range(sibling):
        node = node.getnext()
        while node is not None and not isinstance(node.tag, str):
            node = node.getnext()
        if node is None or (anchors is not None and node in anchors):
            return None
    return node


def capture_value(el, capture: str, attribute: str | None) -> str:
    if el is None:
        return ""
    if capture == "attr":
        return el.get(attribute) or ""
    return field_text(el)


def _capture_attrs(el) -> list[str]:
    """Attributes worth a column of their own: the tag's canonical one
    (`a` -> href, `img` -> src, `time` -> datetime) and a `title`, which
    is where a card keeps the untruncated version of the text it shows."""
    out = []
    primary = CAPTURE_ATTRS.get(el.tag if isinstance(el.tag, str) else "")
    if primary and el.get(primary):
        out.append(primary)
    if el.get("title") and el.get("title").strip():
        out.append("title")
    return out


def _candidate_fields(record) -> list:
    out = []
    for el in record.iter():
        if not isinstance(el.tag, str) or el.tag in SKIP_TAGS or el is record:
            continue
        if is_decoration(el):
            continue
        if _is_text_leaf(el) or _capture_attrs(el):
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
    if not ancestors:
        # A direct child of the scope is addressed as one, ahead of any
        # descendant form that could also reach a namesake nested deeper.
        out = [f"> {segment}" for segment in own] + out
        direct_positional = _positional(el)
        if direct_positional:
            out.append(f"> {direct_positional}")
    # A wrapper with no class of its own still anchors by position: the
    # cells of a table row and the `h3` above a product title are the
    # normal case, not the exception, and without `td:nth-of-type(3) > a`
    # every linked table column and every titled card was unreachable.
    anchors_by_ancestor = [
        [s for s in _own_segments(ancestor) if s != ancestor.tag]
        + ([_positional(ancestor)] if _positional(ancestor) else [])
        for ancestor in ancestors
    ]
    for anchors in anchors_by_ancestor:
        for anchor in anchors:
            for segment in own:
                out.append(f"{anchor} {segment}")
                out.append(f"{anchor} > {segment}")

    positional = _positional(el)
    if positional:
        out.append(positional)
        for anchors in anchors_by_ancestor:
            for anchor in anchors:
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


def _resolve(locator: str, scope: list) -> list | None:
    """The element each scope element yields for this locator, or None if
    any resolves it ambiguously. `None` entries mark absence, which is
    allowed -- that is what makes a field optional rather than invalid.
    An empty locator is the scope element itself (a `dd` that is the
    whole definition)."""
    if locator == "":
        return list(scope)
    # A class segment built from the element's own attributes (`_own_segments`)
    # is not guaranteed to be valid CSS: a Tailwind arbitrary-value class like
    # `bg-[#F4F4F4]!` (corpus/chatgpt.html) round-trips through `f"{tag}.{cls}"`
    # unescaped and `cssselect` rejects it. Treat that the same as any other
    # candidate that fails to resolve, rather than letting it crash the whole
    # build -- `selector.py`'s `_compile` already applies the same guard for
    # record selectors.
    try:
        xpath = relative_locator(locator)
    except Exception:
        return None
    resolved = []
    for element in scope:
        if element is None:
            resolved.append(None)
            continue
        try:
            hits = xpath(element)
        except Exception:
            return None
        if len(hits) > 1:
            return None
        resolved.append(hits[0] if hits else None)
    return resolved


def _value_of(el, attribute: str | None) -> str:
    return capture_value(el, "attr" if attribute else "text", attribute)


def _dominant_type(values: list[str]) -> str:
    present = [classify(v).type for v in values if v]
    return Counter(present).most_common(1)[0][0] if present else "EMPTY"


# An attribute's type follows from what the attribute IS, not from how
# its value happens to look: a relative `href` like `item?id=496520` is a
# URL by construction, even though as text it classifies as TEXT.
ATTRIBUTE_TYPES = {"href": "URL", "src": "URL", "datetime": "DATETIME"}
_ATTRIBUTE_SUFFIX = {"href": "url", "src": "image"}


def _column_type(values: list[str], attribute: str | None) -> str:
    return ATTRIBUTE_TYPES.get(attribute or "", None) or _dominant_type(values)


def _cell_index(resolved: list, records: list) -> int | None:
    """Which table column a field lives in: the position, among the
    record's `td`/`th` children, of the cell that contains the field.

    Works for a value nested inside the cell (`td > a`, `td > span.nowrap`)
    as well as for the bare cell, which is what lets a `th` header name it.
    Mapping only bare `td:nth-of-type(k)` locators lost every linked column:
    the IANA registry's `Reference` and Wikipedia's `Location`."""
    for i, el in enumerate(resolved):
        if el is None:
            continue
        record = records[i]
        node = el
        while node is not None and node.getparent() is not record:
            node = node.getparent()
        if node is None or node.tag not in ("td", "th"):
            return None
        cells = [c for c in record if isinstance(c.tag, str) and c.tag in ("td", "th")]
        return cells.index(node)
    return None


def _unique(names: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: dict[str, int] = {}
    out = []
    for name, source in names:
        seen[name] = seen.get(name, 0) + 1
        out.append((name if seen[name] == 1 else f"{name}_{seen[name]}", source))
    return out


def _shape(record) -> tuple:
    """Direct children with their own children's tags, so a row that is
    typical in cell count but not in cell content is not mistaken for the
    typical row. Wikipedia's population table opens with a `World` row
    whose name sits in `td > b > span`; every country's sits in `td > a`.
    Counting only `td` made `World` the representative, and the one
    locator that reached its name resolved nowhere else."""
    return tuple(
        (c.tag, tuple(g.tag for g in c if isinstance(g.tag, str) and g.tag not in SKIP_TAGS))
        for c in record
        if isinstance(c.tag, str) and c.tag not in SKIP_TAGS
    )


def _representative_indices(records: list) -> list[int]:
    """Which records to enumerate field candidates from.

    Never just the first one. On the Wikipedia population table
    `records[0]` is the `th` header row, so every candidate came out as
    `th:nth-of-type(k)` and resolved in exactly one of 196 rows; the names
    were right only because the header-row heuristic happened to fire on
    the same row. The record with the MODAL children shape is the typical
    one. The record with the most children is added when its shape
    differs, so an optional field that the typical record lacks is still
    seen at all."""
    shapes = [() if r is None else _shape(r) for r in records]
    present = Counter(s for s in shapes if s)
    if not present:
        return []
    modal = present.most_common(1)[0][0]
    typical = shapes.index(modal)
    widest = max(range(len(records)), key=lambda i: len(shapes[i]))
    return [typical] if shapes[widest] == modal else [typical, widest]


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
        _, values, attribute, *_ = column
        present = [v for v in values if v]
        # Seen once is not a pattern -- the same bar `min_cluster_size`
        # sets for a repeated structure. This is what keeps a header row's
        # `th` cells from becoming fields of the data rows.
        if len(present) < MIN_FIELD_PRESENCE:
            continue
        # A constant `title` is furniture too (`title="upvote"` on every
        # vote arrow); a constant href or src is not, since a link's
        # destination is data even when every record points to one place.
        furniture = (
            attribute in (None, "title")
            and len(present) == len(values)
            and len(set(present)) == 1
            and _dominant_type(values) in ("TEXT", "EMPTY")
        )
        if not furniture:
            kept.append(column)
    return kept


def discover(records: list, span: int = 1) -> list[FieldSpec]:
    """Fields shared by every record in `records`, which must be elements
    of the original document.

    With `span > 1` a record is the anchor plus its following siblings, and
    each of those siblings is a scope of its own: the Hacker News subtext
    row is scope 1 of the `tr.athing` anchor, a glossary `dd` is scope 1
    of its `dt`. A scope element that is itself a text leaf is a candidate
    with the empty locator -- the `dd` is the definition, not a wrapper
    around one."""
    if not records:
        return []
    anchors = set(records)

    seen: set[tuple] = set()
    columns: list[tuple] = []
    for offset in range(span):
        scope = [scoped_element(r, offset, anchors) for r in records]
        for source_index in _representative_indices(scope):
            source = scope[source_index]
            candidates = _candidate_fields(source)
            # A scope that is itself a text leaf is the value: the `dd`
            # that is the whole definition, the `dt` that is the term. A
            # one-wide record is not its own field -- the executor already
            # yields `_text` when nothing else exists.
            if (offset or span > 1) and _is_text_leaf(source) and field_text(source):
                candidates.insert(0, source)
            for el in candidates:
                locator, resolved = None, None
                if el is source:
                    locator, resolved = "", list(scope)
                else:
                    for candidate in _locator_candidates(el, source):
                        found = _resolve(candidate, scope)
                        if found is not None and found[source_index] is el:
                            locator, resolved = candidate, found
                            break
                if locator is None:
                    continue

                signature = tuple(id(r) if r is not None else None for r in resolved)
                captures: list[str | None] = list(_capture_attrs(el))
                # Text nested in a leaf is already part of that leaf's value.
                if not (el is not source and _inside_leaf(el, source)) and any(
                    r is not None and field_text(r) for r in resolved
                ):
                    captures.append(None)
                for capture in captures:
                    if (signature, capture) in seen:
                        continue
                    seen.add((signature, capture))
                    columns.append(
                        (locator, [_value_of(r, capture) for r in resolved], capture, resolved, offset, scope)
                    )

    columns = _prune(columns)[:MAX_FIELDS_PER_RECORD]
    if not columns:
        return []

    rows = [[column[1][i] for column in columns] for i in range(len(records))]
    types = [_column_type(column[1], column[2]) for column in columns]
    first_index = [next(i for i, r in enumerate(column[3]) if r is not None) for column in columns]
    first_elements = [column[3][i] for column, i in zip(columns, first_index)]
    scopes = [column[5][i] for column, i in zip(columns, first_index)]
    peers = [column[3] for column in columns]
    names = resolve_names(first_elements, rows, types, scopes, peers)

    header = table_header_cells(records)
    if header:
        named = []
        for (name, source), column in zip(names, columns):
            cell = _cell_index(column[3], records)
            if cell is not None and cell < len(header) and header[cell]:
                # The bare column name belongs to the cell's text; a flag
                # image or a link in the same cell is `location_image`,
                # `location_url`, never `location` with the text as
                # `location_2`.
                suffix = _ATTRIBUTE_SUFFIX.get(column[2], column[2]) if column[2] else None
                base = slugify(header[cell])
                named.append((f"{base}_{suffix}" if suffix else base, "th"))
            else:
                named.append((name, source))
        names = named

    # A link carries two values -- its text and its href -- and both were
    # emitted as columns above. The attribute column takes the text
    # column's name plus a suffix, so a consumer sees `title` and
    # `title_url`, not `title` and `title_2`.
    text_name_by_element = {id(c[3]): n for (n, _), c in zip(names, columns) if c[2] is None}
    names = [
        (f"{text_name_by_element[id(c[3])]}_{_ATTRIBUTE_SUFFIX.get(c[2], c[2])}", source)
        if c[2] and id(c[3]) in text_name_by_element and source != "th"
        else (name, source)
        for (name, source), c in zip(names, columns)
    ]
    names = _unique(names)

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
            sibling=offset,
        )
        for (name, source), (locator, values, attribute, _, offset, _scope), field_type in zip(
            names, columns, types
        )
    ]


__all__ = ["FieldSpec", "capture_value", "discover", "field_text", "is_decoration", "relative_locator", "scoped_element"]
