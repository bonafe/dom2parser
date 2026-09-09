"""`build_families` closes a real gap in `select_top_level_clusters`:
that function picks each `Cluster` independently, competing for one
shared `max_clusters` budget by score alone, so a low-scoring variant of
an otherwise highly relevant repeated structure can be silently dropped
even though it shares the exact DOM shape of a high-scoring variant that
did make the cut.

Verified against examples/bancodobrasil.html: at the default
`max_clusters=10`, the 12 `EMPTY | TEXT | EMPTY | EMPTY` category-header
rows ("Restaurantes", "Pagamentos/Créditos", ...) disappear entirely from
`select_top_level_clusters`'s output, even though they share their exact
DOM shape+path with the 122 `DATE | TEXT | CURRENCY | MONEY` transaction
rows -- the single highest-ranked cluster on the page.
"""

from pathlib import Path

from lxml import etree

from dom2parser.cluster.families import build_families
from dom2parser.cluster.rank import rank_clusters, select_top_level_clusters
from dom2parser.cluster.roles import ROLE_PRIMARY, ROLE_SECTION, ROLE_SUMMARY
from dom2parser.cluster.siblings import cluster_siblings
from dom2parser.compact.paths import describe_path
from dom2parser.fingerprint.hashattrs import find_uniform_build_artifact_attrs
from dom2parser.fingerprint.structural import filter_meaningful_candidates
from dom2parser.html_io import load_html_file
from dom2parser.sanitize import full_sanitize

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def _families_for(path, max_clusters=10):
    root = load_html_file(path)
    clean = full_sanitize(root)
    build_artifacts = find_uniform_build_artifact_attrs(clean)
    all_elements = list(clean.iter(etree.Element))
    candidates = filter_meaningful_candidates(all_elements, build_artifacts)
    clusters = [c for c in cluster_siblings(candidates, build_artifacts) if c.count >= 2]
    ranked = rank_clusters(clusters)
    selected = select_top_level_clusters(ranked, max_clusters=max_clusters)
    return build_families(selected, ranked)


def _transaction_family(families):
    for family in families:
        if any(m.cluster.count == 122 for m in family.members):
            return family
    return None


def test_section_rows_survive_default_max_clusters_via_family_grouping():
    families = _families_for(EXAMPLES_DIR / "bancodobrasil.html", max_clusters=10)
    family = _transaction_family(families)
    assert family is not None, "the transaction-row family must be selected at all"

    roles_by_count = {m.cluster.count: m.role for m in family.members}
    assert roles_by_count[122] == ROLE_PRIMARY
    assert roles_by_count.get(12) == ROLE_SECTION, (
        "the 12 category-header rows must not be dropped just because they "
        "score low in isolation -- they share the transaction rows' exact "
        "DOM shape and belong in the same family"
    )
    assert roles_by_count.get(3) == ROLE_SUMMARY


def test_container_is_linked_to_the_transaction_family():
    families = _families_for(EXAMPLES_DIR / "bancodobrasil.html", max_clusters=10)
    family = _transaction_family(families)
    assert family.container_path is not None
    assert "lancamentos" in family.container_path
    assert family.container_count == 2


def test_absorbed_container_does_not_also_appear_as_its_own_family():
    families = _families_for(EXAMPLES_DIR / "bancodobrasil.html", max_clusters=25)
    family = _transaction_family(families)
    assert family.container_path is not None

    for other in families:
        other_path = describe_path(other.primary.cluster.elements[0]) if other.primary.cluster.elements else None
        assert not (
            other_path == family.container_path and other.primary.cluster.count == family.container_count
        ), "the container cluster should be absorbed, not double-rendered as its own family"


def test_families_with_a_shared_fingerprint_but_different_ancestor_paths_stay_separate():
    # div.limites > div.textoItem and div.totalFatura > div.textoItem
    # collide on DOM fingerprint (same tag/class identity) but live under
    # different, differently-classed parents -- they must not be merged
    # into one family just because cluster_siblings() bucketed them
    # together upstream.
    families = _families_for(EXAMPLES_DIR / "bancodobrasil.html", max_clusters=25)
    textoitem_families = [
        f for f in families
        if f.primary.cluster.elements and f.primary.cluster.elements[0].get("class") == "textoItem"
    ]
    assert len(textoitem_families) == 2, "limites and totalFatura textoItem must stay in separate families"

    paths = {describe_path(f.primary.cluster.elements[0]) for f in textoitem_families}
    assert len(paths) == 2, "the two families must report distinct ancestor paths"
