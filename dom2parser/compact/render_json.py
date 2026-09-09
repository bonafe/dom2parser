"""Fase H: render selected families into the JSON format sketched in the
spec (node/count/signature/examples clusters). A family with a single
member and no linked container keeps the original flat dict shape
(path/count/signature/examples/optional_fields/rank_score) for backward
compatibility; a family with several role variants and/or a linked
container is rendered as a nested dict (`container`, `members: [...]`)."""

from __future__ import annotations

from ..cluster.siblings import optional_fields
from ..dom_utils import collapse_whitespace, direct_children_text, full_text
from .paths import describe_path
from .render_text import MAX_FIELD_LEN, MAX_TEXT_LEN, _describe_field_key


def _example_value(el, content_signature: tuple[str, ...]):
    if len(content_signature) > 1:
        return [collapse_whitespace(t)[:MAX_FIELD_LEN] for t in direct_children_text(el)]
    return collapse_whitespace(full_text(el))[:MAX_TEXT_LEN]


def _member_dict(member) -> dict:
    cluster = member.cluster
    examples = []
    for i in member.sample.indices:
        el = cluster.elements[i]
        examples.append(
            {
                "value": _example_value(el, cluster.content_signature),
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


def render_family(family) -> dict:
    path = describe_path(family.primary.cluster.elements[0]) if family.primary.cluster.elements else None

    if len(family.members) == 1 and family.container_path is None:
        member = family.members[0]
        body = _member_dict(member)
        del body["role"]
        return {"path": path, **body}

    return {
        "path": path,
        "container": (
            {"path": family.container_path, "count": family.container_count}
            if family.container_path is not None
            else None
        ),
        "members": [_member_dict(member) for member in family.members],
    }


def render(families: list) -> list[dict]:
    return [render_family(family) for family in families]
