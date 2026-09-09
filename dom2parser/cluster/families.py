"""Fase F/G (new): group the already-ranked `Cluster`s that share a DOM
structural fingerprint (`structural_key`) -- i.e. the same repeated
element, split by `cluster_siblings()` into several content-signature
variants -- into one `Family`, and link an enclosing "container" cluster
(e.g. a wrapper `div` that repeats once per section/page) to the repeater
nested inside it.

This closes a real gap in `select_top_level_clusters`: that function picks
each `Cluster` independently, competing for one shared `max_clusters`
budget by score alone. A low-scoring variant of an otherwise highly
relevant repeated structure (a page's category-header rows, or its
subtotal/blank rows) can lose that competition and be silently dropped,
even though it belongs to the exact same repeated structure as a
high-scoring variant that did make the cut -- verified on
examples/bancodobrasil.html, where the 12 `EMPTY | TEXT | EMPTY | EMPTY`
category-header rows disappear entirely from the default output even
though the 122 `DATE | TEXT | CURRENCY | MONEY` transaction rows sharing
their exact DOM shape are the single highest-ranked cluster on the page.

So `build_families` looks past `selected` into the full `ranked` list to
pull in same-`structural_key` siblings regardless of their independent
rank, up to a small cap.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..compact.paths import describe_path
from ..dom_utils import direct_children_text
from . import roles
from .rank import ClusterScore, is_rich_signature
from .siblings import Cluster

DEFAULT_MAX_VARIANTS_PER_FAMILY = 5
CONTAINER_COVERAGE_THRESHOLD = 0.8


@dataclass
class FamilyMember:
    cluster_score: ClusterScore
    role: str
    sample: object = None  # sampling.representative.Sample, attached later

    @property
    def cluster(self) -> Cluster:
        return self.cluster_score.cluster


@dataclass
class Family:
    family_key: tuple
    members: list[FamilyMember] = field(default_factory=list)
    container_path: str | None = None
    container_count: int | None = None

    @property
    def primary(self) -> FamilyMember:
        return self.members[0]


def _sample_text(cluster: Cluster) -> tuple[str, ...]:
    if not cluster.elements:
        return ()
    return tuple(direct_children_text(cluster.elements[0]))


def _pick_primary(members: list[ClusterScore]) -> ClusterScore:
    """The primary/dominant member of a family is its most content-bearing
    variant, never merely its most numerous one -- a page's blank spacer
    rows can easily outnumber its real records (bancodobrasil.html has 14
    all-EMPTY rows vs. 3 real header/id rows sharing the same shape), so
    raw `count` must never be allowed to outrank actual informativeness."""

    def informativeness(cs: ClusterScore) -> tuple:
        signature = cs.cluster.content_signature
        not_all_empty = bool(signature) and not all(t == "EMPTY" for t in signature)
        non_generic = sum(1 for t in signature if t not in ("EMPTY", "TEXT", "URL"))
        return (not_all_empty, non_generic, cs.score)

    return max(members, key=informativeness)


def _family_key(cs: ClusterScore) -> tuple:
    """Two clusters belong to the same family when they share both a DOM
    fingerprint (`structural_key` -- tolerant of optional/missing fields,
    see cluster.siblings) AND the same rendered ancestor path. The
    fingerprint alone is not enough: it deliberately ignores an element's
    own children shape once it has a class/id/testid identity (so a
    3-field and a 4-field `div.textoItem` still count as "the same kind of
    node" for clustering), which means two elements with the SAME class
    but sitting under DIFFERENT, differently-classed parents (e.g.
    `div.limites > div.textoItem` vs `div.totalFatura > div.textoItem`)
    can collide on `structural_key` while being unrelated locations on the
    page. `describe_path` walks the true DOM ancestor chain (including
    parent class/id), so requiring it to match too rules out that false
    merge while still uniting genuine same-slot variants (verified: on
    bancodobrasil.html, the transaction/section/summary/empty row variants
    of `tr > td > div.lancamentos > table > tbody > tr` all render the
    identical path string)."""
    path = describe_path(cs.cluster.elements[0]) if cs.cluster.elements else None
    return (cs.cluster.structural_key, path)


def _group_by_family_key(scored: list[ClusterScore]) -> dict[tuple, list[ClusterScore]]:
    groups: dict[tuple, list[ClusterScore]] = {}
    for cs in scored:
        groups.setdefault(_family_key(cs), []).append(cs)
    return groups


def _is_homogeneous_location(cluster: Cluster) -> bool:
    """True if every element of `cluster` shares the same true ancestor
    path. `cluster_siblings()` groups purely by DOM fingerprint + content
    signature, which (like `_family_key`'s docstring above) can conflate
    elements from genuinely different page locations that happen to share
    a bare class/tag identity and field count -- e.g. bancodobrasil.html's
    `div.textoItem` fingerprint bucket ends up holding one element that is
    truly `div.limites > div.textoItem` and another that is truly
    `div.programaRelacionamento > div.textoItem`, both 2-field TEXT|TEXT.
    Such a cluster cannot be trusted as a "container" -- there is no single
    honest path to report for it, and a vote against one of its elements
    (a real ancestor relationship for that specific element) says nothing
    about the cluster as a whole."""
    if not cluster.elements:
        return True
    first_path = describe_path(cluster.elements[0])
    return all(describe_path(el) == first_path for el in cluster.elements[1:])


def _find_container(
    family_elements: list,
    ranked: list[ClusterScore],
    family_key: tuple,
    excluded_keys: set,
) -> ClusterScore | None:
    """A container is another cluster (different DOM shape) that most
    closely wraps this family's elements -- e.g. `div.lancamentos`
    (count=2, a single TEXT blob) wrapping the 137 `tr` rows of the
    `tr > td > div.lancamentos > table > tbody > tr` family.

    For each family element, walks up its ancestor chain and votes for
    whichever candidate cluster owns the FIRST (nearest) ancestor found --
    not just any sufficiently-covering ancestor -- so a coarse, many-levels
    -up wrapper (e.g. the outer page section that happens to structurally
    contain the entire repeated table many levels down) never outranks a
    tighter, more specific one, mirroring the same "nearest wrapper, not
    just any wrapper" rationale `select_top_level_clusters` already
    documents for descendant suppression."""
    if not family_elements:
        return None

    candidates = [
        cs for cs in ranked
        if _family_key(cs) != family_key
        and _family_key(cs) not in excluded_keys
        and not is_rich_signature(cs.cluster.content_signature)
        and _is_homogeneous_location(cs.cluster)
    ]
    if not candidates:
        return None

    element_owner: dict[int, ClusterScore] = {}
    for cs in candidates:
        for el in cs.cluster.elements:
            element_owner[id(el)] = cs

    votes: Counter = Counter()
    for el in family_elements:
        node = el.getparent()
        while node is not None:
            owner = element_owner.get(id(node))
            if owner is not None:
                votes[id(owner)] += 1
                break
            node = node.getparent()

    if not votes:
        return None

    winner_id, winner_votes = votes.most_common(1)[0]
    if winner_votes / len(family_elements) < CONTAINER_COVERAGE_THRESHOLD:
        return None
    return next(cs for cs in candidates if id(cs) == winner_id)


def build_families(
    selected: list[ClusterScore],
    ranked: list[ClusterScore],
    max_variants_per_family: int = DEFAULT_MAX_VARIANTS_PER_FAMILY,
) -> list[Family]:
    """Build one `Family` per distinct family key (`_family_key`) present
    in `selected`, preserving `selected`'s relevance order (first-seen key
    wins position). Each family may pull in extra same-key variants from
    `ranked` that didn't independently make `selected`, and may absorb a
    container cluster (excluded from becoming its own family)."""
    selected_by_key = _group_by_family_key(selected)
    ranked_by_key = _group_by_family_key(ranked)

    already_selected_ids = {id(cs) for cs in selected}

    ordered_keys: list[tuple] = []
    for cs in selected:
        key = _family_key(cs)
        if key not in ordered_keys:
            ordered_keys.append(key)

    families: list[Family] = []
    absorbed_keys: set = set()

    for key in ordered_keys:
        members = list(selected_by_key[key])
        extra = [cs for cs in ranked_by_key.get(key, []) if id(cs) not in already_selected_ids]
        extra.sort(key=lambda cs: cs.score, reverse=True)
        members.extend(extra[:max_variants_per_family])

        primary_cs = _pick_primary(members)
        primary_signature = primary_cs.cluster.content_signature

        family_members = [FamilyMember(cluster_score=primary_cs, role=roles.ROLE_PRIMARY)]
        others = [cs for cs in members if cs is not primary_cs]
        others.sort(key=lambda cs: cs.cluster.count, reverse=True)
        for cs in others:
            role = roles.classify_role(
                cs.cluster.content_signature,
                primary_signature,
                sample_texts=_sample_text(cs.cluster),
            )
            family_members.append(FamilyMember(cluster_score=cs, role=role))

        family = Family(family_key=key, members=family_members)

        family_elements = [el for cs in members for el in cs.cluster.elements]
        container = _find_container(family_elements, ranked, key, absorbed_keys)
        if container is not None:
            family.container_path = _describe_container(container.cluster)
            family.container_count = container.cluster.count
            absorbed_keys.add(_family_key(container))

        families.append(family)

    # A family's container might share a family key with another
    # already-selected top-level cluster (e.g. the container itself was
    # independently rich enough to be selected on its own merit) -- drop
    # it from the output now that it's represented via container_path.
    return [f for f in families if f.family_key not in absorbed_keys]


def _describe_container(cluster: Cluster) -> str:
    return describe_path(cluster.elements[0]) if cluster.elements else "?"


__all__ = ["Family", "FamilyMember", "build_families"]
