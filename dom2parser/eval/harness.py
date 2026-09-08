"""Runs the pipeline built so far (basic sanitize -> fingerprint -> content
signature -> cluster -> rank) against a real HTML document and checks the
result against tests/fixtures/ground_truth.yaml's annotations.

Deliberately uses the *basic* sanitizer (strip.sanitize: scripts/styles/
comments/data-URIs only), not the full nav/widget-removing pipeline
(sanitize.full_sanitize) -- ranking's job is exactly to tell relevant
content apart from boilerplate that survived sanitization (or that a
different site's markup wouldn't have been caught by the denylist
heuristics in boilerplate.py at all), so this harness tests ranking on its
own merits rather than on sanitize.boilerplate's coverage.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree
from lxml.cssselect import CSSSelector

from ..fingerprint.hashattrs import find_uniform_build_artifact_attrs
from ..fingerprint.structural import filter_meaningful_candidates
from ..sanitize.strip import sanitize as basic_sanitize
from ..cluster.siblings import cluster_siblings
from ..cluster.rank import rank_clusters

MIN_CLUSTER_SIZE = 2


@dataclass
class RankCheckResult:
    file: str
    relevant_best_rank: int | None
    noise_best_rank: int | None

    @property
    def passed(self) -> bool:
        if self.relevant_best_rank is None:
            return False
        if self.noise_best_rank is None:
            return True
        return self.relevant_best_rank < self.noise_best_rank


def discover_and_rank(root: etree._Element):
    clean = basic_sanitize(root)
    build_artifacts = find_uniform_build_artifact_attrs(clean)
    all_elements = list(clean.iter(etree.Element))
    candidates = filter_meaningful_candidates(all_elements, build_artifacts)
    clusters = [c for c in cluster_siblings(candidates, build_artifacts) if c.count >= MIN_CLUSTER_SIZE]
    return clean, rank_clusters(clusters)


def _best_rank_matching(scored, target_elements: set) -> int | None:
    for i, cs in enumerate(scored):
        if any(el in target_elements for el in cs.cluster.elements):
            return i
    return None


def check_ranking(root: etree._Element, entry: dict) -> RankCheckResult:
    clean, scored = discover_and_rank(root)

    def elements_for(selectors: list[dict]) -> set:
        found = set()
        for item in selectors:
            found.update(CSSSelector(item["selector"])(clean))
        return found

    relevant_elements = elements_for(entry.get("relevant", []))
    noise_elements = elements_for(entry.get("noise", []))

    relevant_rank = _best_rank_matching(scored, relevant_elements) if relevant_elements else None
    noise_rank = _best_rank_matching(scored, noise_elements) if noise_elements else None

    return RankCheckResult(file=entry["file"], relevant_best_rank=relevant_rank, noise_best_rank=noise_rank)
