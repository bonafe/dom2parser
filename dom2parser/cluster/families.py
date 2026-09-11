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

It also corrects a related pre-existing issue in `cluster_siblings()`:
since that function groups purely by DOM fingerprint + content signature,
with no notion of "true ancestor location", a single `Cluster` can
already span two genuinely unrelated places on the page that happen to
collide on both (see `_split_by_true_path`). Every cluster is resolved
into homogeneous, honestly-scored per-location pieces before any
family/role/container decision is made -- otherwise elements from one
location would get silently misfiled into another location's family.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..compact.paths import describe_path, location_key
from ..dom_utils import direct_children_text
from . import roles
from .rank import ClusterScore, is_rich_signature, score_cluster
from .siblings import Cluster

DEFAULT_MAX_VARIANTS_PER_FAMILY = 5
CONTAINER_COVERAGE_THRESHOLD = 0.8
MIN_RESOLVED_CLUSTER_SIZE = 2


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
    """The primary/dominant member of a family is its most common
    non-degenerate variant -- excluding all-EMPTY signatures (a page's
    blank spacer rows can easily outnumber its real records:
    bancodobrasil.html has 14 all-EMPTY rows vs. 3 real header/id rows
    sharing the same shape), raw `count` decides it.

    Type-richness (`non_generic`) is only a tie-break for near-equal
    counts, never allowed to override count on its own -- otherwise a
    single misclassified field in a handful of otherwise-ordinary records
    can hijack "primary" away from the page's actual dominant record type.
    Verified on bancodobrasil_2.html: 2 transaction rows whose description
    happens to start with a digit ("2 LAB SANTA P PARC 02/02...") get one
    field classified as COUNT_LABELED instead of TEXT, which used to make
    that 2-row variant "richer" (4 non-generic fields vs. 3) than the 140
    real transaction rows it's actually a minor content variant of --
    count must win first so the 140-row pattern stays primary and the
    2-row one is labeled a `variant` of it instead."""

    def informativeness(cs: ClusterScore) -> tuple:
        signature = cs.cluster.content_signature
        not_all_empty = bool(signature) and not all(t == "EMPTY" for t in signature)
        non_generic = sum(1 for t in signature if t not in ("EMPTY", "TEXT", "URL"))
        return (not_all_empty, cs.cluster.count, non_generic, cs.score)

    return max(members, key=informativeness)


def _split_by_true_path(cs: ClusterScore, cache: dict) -> list[ClusterScore]:
    """`cluster_siblings()` groups elements by DOM fingerprint + content
    signature alone -- it has no notion of "true ancestor location", so a
    single `Cluster` can already contain elements from two genuinely
    different places on the page that happen to share both a fingerprint
    and a signature (verified on bancodobrasil_2.html: its all-EMPTY
    `tr(td,td,td,td)` cluster holds 11 rows truly inside
    `div.lancamentos` plus 1 truly inside the outer `#fatura2 > table`,
    and its all-TEXT one similarly mixes 2 `div.lancamentos` rows with 1
    outer-table row). Trusting `elements[0]`'s path for the whole cluster
    (as `_family_key` does) would then silently misfile the *other*
    elements into the wrong family. Split any such heterogeneous cluster
    into one homogeneous piece per true location (`location_key`, which
    already masks per-instance ids/testids so a virtualized list's
    `list-item-N` wrappers don't count as N different places), re-scored
    so each piece can be ranked/selected on its own honest merits."""
    cluster = cs.cluster
    if not cluster.elements:
        return [cs]

    groups: dict[tuple, list] = defaultdict(list)
    for el in cluster.elements:
        groups[location_key(el, cache=cache)].append(el)
    if len(groups) == 1:
        return [cs]

    pieces = []
    for elements in groups.values():
        sub_cluster = Cluster(
            structural_key=cluster.structural_key,
            content_signature=cluster.content_signature,
            elements=elements,
        )
        pieces.append(score_cluster(sub_cluster))
    return pieces


def _resolve_by_true_path(scored: list[ClusterScore], cache: dict | None = None) -> tuple[list[ClusterScore], dict]:
    """Split every cluster in `scored` at most once, returning both the
    flat resolved list and a map from each original cluster's `id()` to
    its resolved pieces -- so a caller holding a second list that shares
    objects with `scored` (e.g. `selected`, which is always a sub-list of
    `ranked` by identity) can look up the SAME piece objects instead of
    re-splitting and getting fresh, differently-identified duplicates for
    what is really the same homogeneous group."""
    if cache is None:
        cache = {}
    resolved: list[ClusterScore] = []
    origin: dict[int, list[ClusterScore]] = {}
    for cs in scored:
        pieces = [p for p in _split_by_true_path(cs, cache) if p.cluster.count >= MIN_RESOLVED_CLUSTER_SIZE]
        origin[id(cs)] = pieces
        resolved.extend(pieces)
    return resolved, origin


def _resolve_selected(selected: list[ClusterScore], origin: dict, cache: dict) -> list[ClusterScore]:
    resolved = []
    seen_ids = set()
    for cs in selected:
        pieces = origin.get(id(cs))
        if pieces is None:
            # Defensive fallback -- shouldn't happen in practice, since
            # `selected` is always a sub-list of `ranked` by identity.
            pieces = [p for p in _split_by_true_path(cs, cache) if p.cluster.count >= MIN_RESOLVED_CLUSTER_SIZE]
        for piece in pieces:
            if id(piece) not in seen_ids:
                seen_ids.add(id(piece))
                resolved.append(piece)
    return resolved


def _family_key(cs: ClusterScore, cache: dict) -> tuple:
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
    page. `location_key` walks the true DOM ancestor chain (including
    parent class/id), so requiring it to match too rules out that false
    merge while still uniting genuine same-slot variants (verified: on
    bancodobrasil.html, the transaction/section/summary/empty row variants
    of `tr > td > div.lancamentos > table > tbody > tr` all render the
    identical path) -- and its masking of per-instance ids/testids keeps a
    virtualized list's position index from being mistaken for such a
    difference.

    When the fingerprint has NO identity signal at all (`("shape",)`,
    every class filtered as atomic), `fingerprint_key` had to fall back to
    the exact children-tag tuple, so a row with one optional extra child
    (oss_gov_br_whatsapp.html: 4 chat rows carrying an unread-count badge
    `div` next to the 17 that don't) lands in a different
    `structural_key`. Here the identical true location supplies the
    identity the fingerprint lacked, so the children tuple is dropped from
    the key and that variant joins its family instead of duplicating it
    under the same displayed path."""
    structural = cs.cluster.structural_key
    if len(structural) > 2 and structural[1] == ("shape",):
        structural = structural[:2]
    path = location_key(cs.cluster.elements[0], cache=cache) if cs.cluster.elements else None
    return (structural, path)


def _group_by_family_key(scored: list[ClusterScore], cache: dict) -> dict[tuple, list[ClusterScore]]:
    groups: dict[tuple, list[ClusterScore]] = {}
    for cs in scored:
        groups.setdefault(_family_key(cs, cache), []).append(cs)
    return groups


def _is_homogeneous_location(cluster: Cluster, cache: dict) -> bool:
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
    first_path = location_key(cluster.elements[0], cache=cache)
    return all(location_key(el, cache=cache) == first_path for el in cluster.elements[1:])


def _find_container(
    family_elements: list,
    ranked: list[ClusterScore],
    family_key: tuple,
    excluded_keys: set,
    cache: dict,
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
    documents for descendant suppression.

    `excluded_keys` must include every family key that will itself become
    a top-level family (not just already-absorbed ones) -- otherwise a
    member of some OTHER family can get mistaken for a container. Verified
    on bancodobrasil.html: the transaction family's own `TEXT|TEXT|TEXT|
    TEXT` header-row variant is the literal DOM parent of the
    `td.tituloTabelaLancamento` header cells, which form their own
    separate family; absorbing that header-row variant as the cell
    family's "container" would silently delete the entire transaction
    family it belongs to, since absorption drops a family by its shared
    key, not by individual member."""
    if not family_elements:
        return None

    candidates = [
        cs for cs in ranked
        if _family_key(cs, cache) != family_key
        and _family_key(cs, cache) not in excluded_keys
        and not is_rich_signature(cs.cluster.content_signature)
        and _is_homogeneous_location(cs.cluster, cache)
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
    container cluster (excluded from becoming its own family).

    Both lists are first resolved through `_resolve_by_true_path` --
    `cluster_siblings()` can hand back a single `Cluster` whose elements
    span two genuinely different page locations (see that function's
    docstring), so every cluster is split into per-true-path, honestly
    scored pieces before any family/role/container decision is made.
    `ranked` is resolved once and `selected` derived from the same
    resolution (rather than resolved independently) so the two lists keep
    sharing object identity for their common pieces -- otherwise the same
    homogeneous piece would be split twice into two different objects and
    wrongly appear as its own "extra" duplicate of itself."""
    cache: dict = {}
    ranked, origin = _resolve_by_true_path(ranked, cache)
    selected = _resolve_selected(selected, origin, cache)

    selected_by_key = _group_by_family_key(selected, cache)
    ranked_by_key = _group_by_family_key(ranked, cache)

    already_selected_ids = {id(cs) for cs in selected}

    ordered_keys: list[tuple] = []
    for cs in selected:
        key = _family_key(cs, cache)
        if key not in ordered_keys:
            ordered_keys.append(key)

    # Gather each family's members up front (independent of container
    # detection) so we know, before searching for ANY container, which
    # family keys have a "rich" primary -- a member of such a family (e.g.
    # the transaction family's own `TEXT|TEXT|TEXT|TEXT` header-row
    # variant) must never be absorbed as some OTHER family's container,
    # since absorption drops a family by its shared key: that would
    # silently delete the whole rich family it belongs to just because one
    # of its minor variants also happens to be some other cluster's true
    # DOM parent. A plain, non-rich container-shaped cluster (e.g.
    # `div.lancamentos`, a single TEXT blob) stays absorbable even if it
    # was independently selected as its own (uninteresting) family.
    members_by_key: dict[tuple, list[ClusterScore]] = {}
    for key in ordered_keys:
        members = list(selected_by_key[key])
        extra = [cs for cs in ranked_by_key.get(key, []) if id(cs) not in already_selected_ids]
        extra.sort(key=lambda cs: cs.score, reverse=True)
        members.extend(extra[:max_variants_per_family])
        members_by_key[key] = members

    rich_family_keys = {
        key for key, members in members_by_key.items()
        if is_rich_signature(_pick_primary(members).cluster.content_signature)
    }

    families: list[Family] = []
    absorbed_keys: set = set()

    for key in ordered_keys:
        members = members_by_key[key]
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
        container = _find_container(family_elements, ranked, key, absorbed_keys | rich_family_keys, cache)
        if container is not None:
            family.container_path = _describe_container(container.cluster, cache)
            family.container_count = container.cluster.count
            absorbed_keys.add(_family_key(container, cache))

        families.append(family)

    # A family's container might share a family key with another
    # already-selected top-level cluster (e.g. the container itself was
    # independently rich enough to be selected on its own merit) -- drop
    # it from the output now that it's represented via container_path.
    return [f for f in families if f.family_key not in absorbed_keys]


def _describe_container(cluster: Cluster, cache: dict) -> str:
    return describe_path(cluster.elements[0], cache=cache) if cluster.elements else "?"


__all__ = ["Family", "FamilyMember", "build_families"]
