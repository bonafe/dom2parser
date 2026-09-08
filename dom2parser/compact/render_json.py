"""Fase H: render selected (cluster, sample) pairs into the JSON format
sketched in the spec (node/count/signature/examples clusters)."""

from __future__ import annotations

from ..dom_utils import collapse_whitespace, direct_children_text, full_text
from ..cluster.siblings import optional_fields
from .paths import describe_path
from .render_text import MAX_FIELD_LEN, MAX_TEXT_LEN, _describe_field_key


def _example_value(el, content_signature: tuple[str, ...]):
    if len(content_signature) > 1:
        return [collapse_whitespace(t)[:MAX_FIELD_LEN] for t in direct_children_text(el)]
    return collapse_whitespace(full_text(el))[:MAX_TEXT_LEN]


def render_cluster(cluster_score, sample) -> dict:
    cluster = cluster_score.cluster
    examples = []
    for i in sample.indices:
        el = cluster.elements[i]
        examples.append(
            {
                "value": _example_value(el, cluster.content_signature),
                "reasons": sample.reasons.get(i, []),
            }
        )

    return {
        "path": describe_path(cluster.elements[0]) if cluster.elements else None,
        "count": cluster.count,
        "signature": list(cluster.content_signature),
        "examples": examples,
        "optional_fields": {
            _describe_field_key(key): {"present": count, "total": cluster.count}
            for key, count in optional_fields(cluster).items()
        },
        "rank_score": cluster_score.score,
    }


def render(selected: list[tuple]) -> list[dict]:
    return [render_cluster(cluster_score, sample) for cluster_score, sample in selected]
