"""Fase H: render selected families as JSON.

Schema 2 is one shape, always. Schema 1 had two mutually exclusive ones --
flat when a family had a single member and no container, nested otherwise
-- distinguished only by which keys were present, and `examples[].value`
was a `str` or a `list[str]` depending on the signature length. Every
consumer had to branch on both, which is exactly the ambiguity that makes
a contract hard to build a parser on.

So: `container` is always present and nullable, `members` is always a
list, and an example's `values` is always an object. When the record's
fields are known the object is keyed by their derived names; when they are
not, it carries the element's text under `_text`, so the type never
changes.

`path_display` is named for what it is. It reads well and locates a
structure for a human, but it is capped at six ancestor levels and carries
`*` masks, so it is not a selector and must never be used as one --
`record_selector.selector` is the verified one.
"""

from __future__ import annotations

from ..cluster.siblings import optional_fields
from ..dom_utils import collapse_whitespace, full_text
from ..parser.executor import compile_record, record_values
from .paths import describe_path
from .render_text import MAX_TEXT_LEN, _describe_field_key

SCHEMA_VERSION = 2


def _example_values(el, compiled) -> dict:
    if compiled is None or not compiled.locators:
        return {"_text": collapse_whitespace(full_text(el))[:MAX_TEXT_LEN]}
    # The sampled element belongs to the family, which may be an inner
    # wrapper of the record; the record's anchor is its nearest ancestor
    # (or itself) among the selector's matches.
    anchor_set = compiled.anchor_set
    node = el
    while node is not None and node not in anchor_set:
        node = node.getparent()
    if node is None:
        return {"_text": collapse_whitespace(full_text(el))[:MAX_TEXT_LEN]}
    return {k: v[:MAX_TEXT_LEN] for k, v in record_values(node, compiled, anchor_set).items()}


def _member_dict(member, compiled, originals) -> dict:
    cluster = member.cluster
    examples = []
    for i in member.sample.indices:
        element = cluster.elements[i]
        examples.append(
            {
                "values": _example_values(originals.get(id(element), element), compiled),
                "reasons": member.sample.reasons.get(i, []),
            }
        )
    return {
        "role": member.role,
        "count": cluster.count,
        "signature": list(cluster.content_signature),
        "examples": examples,
        "optional_fields": {
            _describe_field_key(key): {"present": count, "total": cluster.count}
            for key, count in optional_fields(cluster).items()
        },
        "rank_score": member.cluster_score.score,
    }


def render_family(family, record=None, compiled=None, originals=None) -> dict:
    elements = family.primary.cluster.elements
    return {
        "path_display": describe_path(elements[0]) if elements else None,
        "record_selector": (
            {"selector": record.selector, "span": record.span, "verified": record.verified}
            if record
            else None
        ),
        "container": (
            {"path_display": family.container_path, "count": family.container_count}
            if family.container_path is not None
            else None
        ),
        "fields": [
            {
                "name": f.name,
                "locator": f.locator,
                "type": f.type,
                "capture": f.capture,
                "attribute": f.attribute,
                "required": f.required,
                "present": f.present,
                "total": f.total,
                "name_source": f.name_source,
                "sibling": f.sibling,
            }
            for f in (record.fields if record else [])
        ],
        "members": [_member_dict(member, compiled, originals or {}) for member in family.members],
    }


def render(families: list, spec=None, by_family=None, originals=None, root=None) -> dict:
    by_family = by_family or {}
    structures = []
    for position, family in enumerate(families):
        record = by_family.get(position)
        compiled = compile_record(record, root) if record is not None and root is not None else None
        structures.append(render_family(family, record, compiled, originals))

    return {
        "schema_version": SCHEMA_VERSION,
        "structures": structures,
        "failures": list(spec.failures) if spec else [],
    }
