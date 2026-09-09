"""dom2parser: compress a large HTML document into a compact structural
representation for an external LLM-driven parser generator to consume.

Public API: `compress(html)`. Everything else in this package is an
implementation detail of the pipeline described in
spec/handoff_parser_html_llm.md and the project plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from .cluster.families import build_families
from .cluster.rank import rank_clusters, select_top_level_clusters
from .cluster.siblings import cluster_siblings
from .compact import render_json as _render_json
from .compact import render_text as _render_text
from .compact.tokens import reduction_report
from .fingerprint.hashattrs import find_uniform_build_artifact_attrs
from .fingerprint.structural import filter_meaningful_candidates
from .html_io import parse_html
from .sanitize import full_sanitize
from .sampling.representative import sample_cluster

DEFAULT_MIN_CLUSTER_SIZE = 2
DEFAULT_MAX_CLUSTERS = 10
DEFAULT_MAX_SAMPLES_PER_CLUSTER = 7


@dataclass
class CompactRepresentation:
    text: str
    json: list
    reduction: dict


def compress(
    html: str,
    max_clusters: int = DEFAULT_MAX_CLUSTERS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    max_samples_per_cluster: int = DEFAULT_MAX_SAMPLES_PER_CLUSTER,
) -> CompactRepresentation:
    root = parse_html(html)
    clean = full_sanitize(root)

    build_artifacts = find_uniform_build_artifact_attrs(clean)
    all_elements = list(clean.iter(etree.Element))
    candidates = filter_meaningful_candidates(all_elements, build_artifacts)
    clusters = [
        c for c in cluster_siblings(candidates, build_artifacts) if c.count >= min_cluster_size
    ]

    ranked = rank_clusters(clusters)
    selected = select_top_level_clusters(ranked, max_clusters=max_clusters)
    families = build_families(selected, ranked)
    for family in families:
        for member in family.members:
            member.sample = sample_cluster(member.cluster, max_samples=max_samples_per_cluster)

    text = _render_text.render(families)
    json_repr = _render_json.render(families)
    reduction = reduction_report(html, text)

    return CompactRepresentation(text=text, json=json_repr, reduction=reduction)
