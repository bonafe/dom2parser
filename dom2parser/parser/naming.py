"""Fase K: give a field a name a human would recognise.

Naming is the one part of parser synthesis that is genuinely semantic, and
therefore the one part a language model would be good at. It is done here
without one anyway, because real pages carry the names already -- the
spec's own worked example points at exactly that:

    td.tituloTabelaLancamento = "Data"
    td.tituloTabelaLancamento = "Transações"

On bancodobrasil.html those four words are a header row sitting among the
records themselves. Where no such evidence exists (oss_gov_br_whatsapp.html,
where every class is a Stylex hash), naming falls back to type and
position and a human renames the field by editing the spec -- which is
cheap, and honest about what was inferred versus what was read off the
page.
"""

from __future__ import annotations

import re
import unicodedata

from ..content.signature import classify
from ..dom_utils import collapse_whitespace, full_text
from ..fingerprint.hashattrs import semantic_class_tokens

# A header row announces the columns, so it is all prose: no dates, no
# money, nothing empty. Records that look like this are rare by
# construction, which is what makes the shape usable as evidence.
_HEADER_MAX_SHARE = 0.1
# A column label is a label, not a sentence. Without this bound the shape
# test alone accepts any prose row: on acervodadostecnicosgovbr.html it
# named a field `data_de_atualizacao_do_arquivo_indisponivel_cabecalho_...`
# off a paragraph that happened to be the only all-text row.
_HEADER_MAX_CHARS = 40
_HEADER_MAX_WORDS = 5


def slugify(text: str) -> str:
    """`Transações` -> `transacoes`. ASCII-folded so the name is usable as
    an identifier in whatever language consumes the extracted records."""
    folded = unicodedata.normalize("NFKD", text or "")
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only).strip("_").lower()
    return slug or "field"


def _looks_like_header(values: list[str]) -> bool:
    return len(values) >= 2 and all(
        v
        and classify(v).type == "TEXT"
        and len(v) <= _HEADER_MAX_CHARS
        and len(v.split()) <= _HEADER_MAX_WORDS
        for v in values
    )


def header_names(rows: list[list[str]]) -> list[str] | None:
    """Column names read off a header row among the records.

    `rows` is one list of field values per record. A row qualifies when
    every cell is non-empty prose while the records as a whole are not --
    the `_HEADER_MAX_SHARE` cap is what distinguishes a header from a page
    whose records are genuinely all text."""
    candidates = [row for row in rows if _looks_like_header(row)]
    if not candidates or len(candidates) > max(1, int(len(rows) * _HEADER_MAX_SHARE)):
        return None
    widest = max(candidates, key=len)
    return [slugify(v) for v in widest] if len(widest) == len(max(rows, key=len)) else None


def table_header_cells(records: list) -> list[str] | None:
    """Column labels from a table's `th` row, in column order, when the
    records are that table's rows.

    Distinct from `header_names`, which finds a header row hiding among
    the records with `td` cells (bancodobrasil.html). Here the header is
    marked up as such -- `th` in a `thead` or a leading row -- so it can be
    read without any shape heuristic. Both the IANA registry and the
    Wikipedia population table name their columns this way, and neither
    got a single name from the cascade until this existed."""
    first = records[0]
    if first.tag != "tr":
        return None
    table = first.getparent()
    while table is not None and table.tag != "table":
        table = table.getparent()
    if table is None:
        return None
    for row in table.iter("tr"):
        cells = [c for c in row if isinstance(c.tag, str) and c.tag in ("th", "td")]
        if cells and all(c.tag == "th" for c in cells):
            # itertext, not text_content: a `<br>` inside a header cell
            # separates words that text_content would glue together
            # (`Source (official or from<br>the United Nations)`).
            return [collapse_whitespace(" ".join(c.itertext())) for c in cells]
    return None


def _shared_prefix_stripped(names: list[str]) -> list[str]:
    """`views_field_title` / `views_field_body` -> `title` / `body`. A
    prefix every sibling field shares carries no information about which
    field is which.

    Only applied to names read off the page. A fallback name is
    `type_position` by construction, so stripping its shared type would
    leave the bare position (`url_1`/`url_2` -> `1`/`2`) and destroy the
    only meaning it had."""
    if len(names) < 2:
        return names
    parts = [n.split("_") for n in names]
    common = 0
    while all(len(p) > common + 1 and p[common] == parts[0][common] for p in parts):
        common += 1
    if not common:
        return names
    stripped = ["_".join(p[common:]) for p in parts]
    if any(not s or s[0].isdigit() for s in stripped):
        return names
    return stripped


# Tags whose meaning HTML itself fixes. `dt`/`dd` are the only names a
# definition list ever offers; the rest are cheap and rarely wrong.
_TAG_NAMES = {
    "dt": "term",
    "dd": "definition",
    "time": "datetime",
    "img": "image",
    "figcaption": "caption",
    "cite": "citation",
    "blockquote": "quote",
    "q": "quote",
    "address": "address",
    "summary": "summary",
    "h1": "title",
    "h2": "title",
    "h3": "title",
    "h4": "title",
    "h5": "title",
    "h6": "title",
}


def _own_name(el, constant) -> tuple[str, str] | None:
    """A name off one element, taking only evidence `constant` accepts."""
    for attr, source in (("itemprop", "itemprop"), ("aria-label", "aria_label")):
        value = el.get(attr)
        if value and value.strip() and constant(attr):
            return slugify(value), source
    classes = semantic_class_tokens(el.get("class", ""))
    if classes and constant("class"):
        return slugify(classes[0]), "class"
    if el.tag in _TAG_NAMES:
        return _TAG_NAMES[el.tag], "tag"
    return None


def _constant_across(peers, depth: int):
    """Whether an attribute has the same value on this field's element in
    every record -- reading `depth` ancestors up, since a name may be
    inherited from a wrapper.

    A name describes the column; a value that changes per record is the
    DATA. On agenciagov's news list every card's link carries
    `aria-label="Estudantes de licenciatura podem se inscrever..."`, and
    taking it literally named the field after one headline. Constancy is
    the difference, and it is measured, not guessed."""

    def constant(attr: str) -> bool:
        seen = set()
        for peer in peers:
            node = peer
            for _ in range(depth):
                node = node.getparent() if node is not None else None
            if node is None:
                continue
            seen.add(node.get(attr))
            if len(seen) > 1:
                return False
        return True

    return constant


def element_name(el, scope=None, peers=()) -> tuple[str, str] | None:
    """A name read off one field element, with the evidence that produced
    it, or None when nothing says what the value is.

    The evidence is often on a wrapper rather than on the leaf: Hacker
    News puts the story title in a bare `a` inside `span.titleline`, and a
    glossary definition is a bare `p` inside the `dd`. So the walk goes up
    to (not including) the scope, and takes the first ancestor that names
    itself -- by class, or by a tag HTML gives a meaning to.

    `peers` are this same field's elements in the other records; evidence
    that differs across them is data, not a name."""
    peers = [p for p in peers if p is not None] or [el]
    own = _own_name(el, _constant_across(peers, 0))
    if own is not None:
        return own
    node, depth = el.getparent(), 1
    while node is not None and node is not scope:
        inherited = _own_name(node, _constant_across(peers, depth))
        if inherited is not None:
            return inherited[0], f"ancestor_{inherited[1]}"
        node, depth = node.getparent(), depth + 1
    if scope is not None and scope is not el and scope.tag in _TAG_NAMES:
        return _TAG_NAMES[scope.tag], "ancestor_tag"
    return None


def resolve_names(
    field_elements: list,
    rows: list[list[str]],
    types: list[str],
    scopes: list | None = None,
    peers: list | None = None,
) -> list[tuple[str, str]]:
    """Names for every field slot, as `(name, source)`.

    Header evidence wins outright when present: it names all slots at once
    and consistently, which per-element evidence cannot guarantee."""
    from_header = header_names(rows)
    if from_header and len(from_header) == len(field_elements):
        return [(name, "header_row") for name in from_header]

    scopes = scopes or [None] * len(field_elements)
    peers = peers or [()] * len(field_elements)
    names, sources = [], []
    for slot, el in enumerate(field_elements):
        derived = element_name(el, scopes[slot], peers[slot]) if el is not None else None
        if derived is None:
            names.append(f"{types[slot].lower()}_{slot + 1}")
            sources.append("type_position")
        else:
            names.append(derived[0])
            sources.append(derived[1])

    read_off_page = [i for i, s in enumerate(sources) if s != "type_position"]
    if len(read_off_page) == len(names):
        names = _shared_prefix_stripped(names)

    # Collisions are left for the caller: a link's text and href columns
    # share a name here on purpose, and the href one is renamed `_url`
    # afterwards. Suffixing now would leave `titleline_2` / `titleline_2_url`.
    return list(zip(names, sources))


def text_of(el) -> str:
    return collapse_whitespace(full_text(el))


__all__ = ["slugify", "resolve_names", "header_names", "text_of"]
