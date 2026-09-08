"""Fase G: pick a small, representative subset of a cluster's elements to
show the LLM -- first/second/middle/penultimate/last (per the spec) plus
any structural/content outliers found within the cluster (Fase G part 2,
cluster.outliers), so real variation isn't hidden by only ever showing the
first N instances.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..cluster.outliers import numeric_field_outlier_indices, text_length_outlier_indices
from ..cluster.siblings import Cluster


def representative_indices(n: int) -> set[int]:
    if n <= 0:
        return set()
    return {0, min(1, n - 1), n // 2, max(0, n - 2), n - 1}


@dataclass
class Sample:
    cluster: Cluster
    indices: list[int]
    reasons: dict[int, list[str]]

    @property
    def elements(self) -> list:
        return [self.cluster.elements[i] for i in self.indices]


def sample_cluster(cluster: Cluster, max_samples: int | None = None) -> Sample:
    n = cluster.count
    reasons: dict[int, list[str]] = {}

    for i in sorted(representative_indices(n)):
        reasons.setdefault(i, []).append("representative-position")
    for i in numeric_field_outlier_indices(cluster):
        reasons.setdefault(i, []).append("numeric-outlier")
    for i in text_length_outlier_indices(cluster):
        reasons.setdefault(i, []).append("text-length-outlier")

    indices = sorted(reasons)
    if max_samples is not None and len(indices) > max_samples:
        # keep representative positions first, then outliers, until the cap
        ordered = sorted(indices, key=lambda i: (0 if "representative-position" in reasons[i] else 1, i))
        indices = sorted(ordered[:max_samples])

    return Sample(cluster=cluster, indices=indices, reasons=reasons)
