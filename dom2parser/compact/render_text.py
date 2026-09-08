"""Fase H: render selected (cluster, sample) pairs into the structured
text format sketched in the spec (`REPEATED STRUCTURE: ... x N`,
`signature: ...`, `examples: [...]`)."""

from __future__ import annotations

from ..dom_utils import collapse_whitespace, direct_children_text, full_text
from ..cluster.siblings import optional_fields
from .paths import describe_path

MAX_FIELD_LEN = 200
MAX_TEXT_LEN = 300


def _example_repr(el, content_signature: tuple[str, ...]):
    if len(content_signature) > 1:
        return [collapse_whitespace(t)[:MAX_FIELD_LEN] for t in direct_children_text(el)]
    return collapse_whitespace(full_text(el))[:MAX_TEXT_LEN]


def _describe_field_key(key: tuple) -> str:
    tag, identity = key
    kind, value = identity
    if kind == "class":
        value = ".".join(value)
    return f"{tag}[{kind}={value}]"


def render_cluster(cluster_score, sample) -> str:
    cluster = cluster_score.cluster
    path = describe_path(cluster.elements[0]) if cluster.elements else "?"
    lines = [f"{path}", f"  count: {cluster.count}"]

    if cluster.content_signature:
        lines.append(f"  signature: {' | '.join(cluster.content_signature)}")

    lines.append("  examples:")
    for i in sample.indices:
        el = cluster.elements[i]
        reasons = ",".join(sample.reasons.get(i, []))
        lines.append(f"    {_example_repr(el, cluster.content_signature)!r}  # {reasons}")

    opt = optional_fields(cluster)
    if opt:
        lines.append("  optional_fields:")
        for key, count in opt.items():
            lines.append(f"    {_describe_field_key(key)}: present in {count}/{cluster.count}")

    return "\n".join(lines)


def render(selected: list[tuple]) -> str:
    """`selected` is a list of (ClusterScore, Sample) pairs, highest-ranked
    first (see cluster.rank.select_top_level_clusters + sampling)."""
    blocks = ["REPEATED STRUCTURES (ranked by relevance):", ""]
    for cluster_score, sample in selected:
        blocks.append(render_cluster(cluster_score, sample))
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"
