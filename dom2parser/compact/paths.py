"""Human-readable ancestor-path descriptions for a cluster, e.g.
`div#fatura2 > div.lancamentos > table > tbody > tr`, used by both
renderers to show the LLM *where* a cluster lives in the document (the
spec's "Relevant DOM path"), and -- via `location_key` -- by
cluster.families to decide whether two elements sit in the same "true
location" of the page.

Each ancestor is described by ONE identity signal (id > data-testid >
semantic classes > bare tag). The problem is that ids and testids are
also where per-INSTANCE keys live: a virtualized list's
`data-testid="list-item-0"`, `"list-item-1"`, ... wrapper, a
server-rendered `<tr id="tx-3f9a2c">`, a slug like `id="item-apple"`.
Taken literally, those make every row of a genuinely repeated structure
look like it lives somewhere different -- shattering the cluster (verified
on oss_gov_br_whatsapp.html: 23 chat rows became 23 singletons) -- and,
just as bad, put a single instance's key into the displayed path, so a
selector derived from it matches ONE row instead of all of them.

So every segment is checked for volatility and, when volatile, its
per-instance part is replaced by `*` in BOTH the grouping key and the
display (`div[data-testid="list-item-*"]`, `tr#tx-*`). Volatility is
decided per segment kind, from value shape first and from DOM evidence
(the element's same-tag siblings) second -- see `_id_like_segment`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..fingerprint.hashattrs import looks_like_random_token, semantic_class_tokens

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# A hex run only counts when it contains a digit, so English words that
# happen to be all a-f (`facade`, `decade`) survive.
_HEX_RUN = r"(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{6,}"
_VOLATILE_RUN_RE = re.compile(f"{_UUID}|{_HEX_RUN}|\\d+")
_MIN_BARE_PREFIX = 3
# Two names sharing a 2-letter prefix is coincidence (`apple`/`avocado`);
# two hundred distinct siblings all starting with the same two letters is
# a generator. MediaWiki's Parsoid stamps `id="mwBlw"`, `id="mwCTE"`, ...
# on every element, which is exactly that shape and defeats the
# separator and length rules below.
_MANY_SIBLINGS = 5


@dataclass(frozen=True)
class PathSegment:
    tag: str
    kind: str  # "id" | "testid" | "class" | "tag"
    value: str  # grouping value; "*" marks a per-instance part
    display: str


def _mask_volatile_runs(value: str) -> str:
    return _VOLATILE_RUN_RE.sub("*", value)


def _shared_prefix(values: list[str]) -> str:
    """Longest common prefix, cut back to the last `-`/`_` separator (so
    `user-john`/`user-jane` yield `user-`, not `user-j`); without any
    separator a short prefix is rejected as coincidence (`apple`/`avocado`
    do not share an `a*` family). A prefix equal to one of the values is
    also rejected: `#list` and `#list-header` are two named things, not an
    enumeration."""
    first, rest = values[0], values[1:]
    n = 0
    while n < len(first) and all(len(v) > n and v[n] == first[n] for v in rest):
        n += 1
    prefix = first[:n]
    if any(len(v) == n for v in values):
        return ""
    sep = max(prefix.rfind("-"), prefix.rfind("_"))
    if sep >= 0:
        return prefix[: sep + 1]
    if len(prefix) >= _MIN_BARE_PREFIX:
        return prefix
    return prefix if len(prefix) >= 2 and len(values) >= _MANY_SIBLINGS else ""


def _same_tag_sibling_values(el, tag: str, attr: str) -> list[str]:
    parent = el.getparent()
    if parent is None:
        return [el.get(attr)]
    return [v for sib in parent if sib.tag == tag for v in (sib.get(attr),) if v]


def _id_like_segment(el, tag: str, kind: str, attr: str, raw: str) -> PathSegment:
    """Volatility for an id/testid value, first rule that fires wins:

    1. Value shape: digit runs, hex runs, UUIDs collapse to `*`
       (`list-item-7` -> `list-item-*`, `fatura2` -> `fatura*`).
    2. Sibling enumeration: if the element's same-tag siblings carry
       DISTINCT values (after 1) that share a common prefix, the value is
       an instance key, not a place (`item-apple`/`item-banana` ->
       `item-*`). Genuinely distinct named siblings (`#header`/`#content`)
       share no prefix and stay apart.
    3. Random keys: distinct sibling values with no prefix at all that
       every one looks generated (`Xk9pQ2`) collapse to a bare `*`."""
    masked = _mask_volatile_runs(raw)
    siblings = _same_tag_sibling_values(el, tag, attr)
    distinct = sorted({_mask_volatile_runs(v) for v in siblings})
    value = masked
    if len(distinct) >= 2:
        prefix = _shared_prefix(distinct)
        if prefix:
            value = prefix + "*"
        elif all(looks_like_random_token(v) for v in siblings):
            value = "*"
    display = f"{tag}#{value}" if kind == "id" else f'{tag}[data-testid="{value}"]'
    return PathSegment(tag=tag, kind=kind, value=value, display=display)


def describe_segment(el) -> PathSegment:
    tag = el.tag if isinstance(el.tag, str) else "?"
    el_id = el.get("id")
    if el_id:
        return _id_like_segment(el, tag, "id", "id", el_id)
    testid = el.get("data-testid")
    if testid:
        return _id_like_segment(el, tag, "testid", "data-testid", testid)
    classes = semantic_class_tokens(el.get("class", ""))
    if classes:
        value = ".".join(_mask_volatile_runs(c) for c in classes[:3])
        return PathSegment(tag=tag, kind="class", value=value, display=f"{tag}.{value}")
    return PathSegment(tag=tag, kind="tag", value="", display=tag)


def describe_segments(el, max_levels: int = 6, cache: dict | None = None) -> tuple[PathSegment, ...]:
    """Innermost-last segments for `el` and up to `max_levels - 1`
    ancestors. `cache` (keyed by node identity) makes repeated lookups on
    the same document cheap; it stores the node alongside its segment so
    lxml keeps the proxy alive and the identity key stays valid."""
    parts = []
    node = el
    while node is not None and len(parts) < max_levels:
        if cache is None:
            segment = describe_segment(node)
        else:
            hit = cache.get(id(node))
            if hit is None:
                hit = (node, describe_segment(node))
                cache[id(node)] = hit
            segment = hit[1]
        parts.append(segment)
        node = node.getparent()
    return tuple(reversed(parts))


def location_key(el, max_levels: int = 6, cache: dict | None = None) -> tuple:
    return tuple((s.tag, s.kind, s.value) for s in describe_segments(el, max_levels, cache))


def describe_path(el, max_levels: int = 6, cache: dict | None = None) -> str:
    return " > ".join(s.display for s in describe_segments(el, max_levels, cache))
