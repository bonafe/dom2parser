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
from dom2parser.cluster.roles import ROLE_PRIMARY, ROLE_SECTION, ROLE_SUMMARY, ROLE_VARIANT
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


def test_heterogeneous_cluster_splits_into_correct_per_location_families():
    # `table(.tabelaValores) > tbody > tr` (TEXT|MONEY rows) is one Cluster
    # object spanning FOUR different real summary tables (totalFatura,
    # limites, resumoReal, resumoDolar) that happen to collide on DOM
    # fingerprint and content signature -- cluster_siblings() lumps them
    # into a single, mislabeled 17-row cluster. Each real location's own
    # row count must survive as its own, correctly-pathed family instead.
    families = _families_for(EXAMPLES_DIR / "bancodobrasil.html", max_clusters=25)
    counts_by_path = {
        describe_path(f.primary.cluster.elements[0]): f.primary.cluster.count
        for f in families
        if f.primary.cluster.elements
    }

    assert counts_by_path.get("td > div.totalFatura > div.textoItem > table.tabelaValores > tbody > tr") == 3
    assert counts_by_path.get("td > div.limites > div.textoItem > table > tbody > tr") == 4
    assert counts_by_path.get("td > div.resumoReal > div.textoItem > table.tabelaValores > tbody > tr") == 5
    assert counts_by_path.get("td > div.resumoDolar > div.textoItem > table.tabelaValores > tbody > tr") == 5


def test_single_occurrence_widgets_that_coincidentally_share_a_signature_are_dropped():
    # div.textoItem itself is a single DOM fingerprint bucket holding SIX
    # elements from six different, non-repeating widgets (totalFatura,
    # limites, resumoReal, resumoDolar, programaRelacionamento,
    # usoExterior). Two pairs of them coincidentally share a content
    # signature too (e.g. both totalFatura's and resumoReal's textoItem
    # reduce to a single TEXT blob), which used to render as a fake
    # "count: 2" repeated structure. Once split by true path, each real
    # location contributes only 1 element -- correctly not a repeated
    # structure at all, so none of them should appear as a family.
    families = _families_for(EXAMPLES_DIR / "bancodobrasil.html", max_clusters=25)
    paths = {
        describe_path(f.primary.cluster.elements[0])
        for f in families
        if f.primary.cluster.elements
    }
    assert "table > tbody > tr > td > div.limites > div.textoItem" not in paths
    assert "table > tbody > tr > td > div.totalFatura > div.textoItem" not in paths


def test_dominant_pattern_stays_primary_despite_a_richer_looking_tiny_outlier():
    # bancodobrasil_2.html: 2 of the 140 real transaction rows have a
    # description that happens to start with a digit ("2 LAB SANTA P PARC
    # 02/02..."), which the content classifier reads as COUNT_LABELED
    # instead of TEXT -- making that 2-row variant's signature "richer"
    # (4 non-generic fields) than the 140-row DATE|TEXT|CURRENCY|MONEY
    # pattern it's actually a minor variant of (3 non-generic fields).
    # Picking "primary" by type-richness alone would let a 2-row content
    # classifier quirk hijack the role away from the page's actual
    # dominant record type.
    families = _families_for(EXAMPLES_DIR / "bancodobrasil_2.html", max_clusters=10)
    family = next(f for f in families if any(m.cluster.count == 140 for m in f.members))

    assert family.primary.cluster.count == 140
    assert family.primary.cluster.content_signature == ("DATE", "TEXT", "CURRENCY", "MONEY")

    roles_by_count = {m.cluster.count: m.role for m in family.members}
    assert roles_by_count.get(2) in (ROLE_VARIANT, ROLE_SUMMARY, ROLE_SECTION)
    assert roles_by_count[2] != ROLE_PRIMARY


def test_family_member_is_never_absorbed_as_another_familys_container():
    # bancodobrasil.html: the transaction family's own TEXT|TEXT|TEXT|TEXT
    # header-row variant is the literal DOM parent of the
    # td.tituloTabelaLancamento header cells, which form their own
    # separate family. Absorbing that header-row variant as the cell
    # family's "container" would silently delete the WHOLE transaction
    # family (absorption drops a family by its shared key, not by
    # individual member) -- so a member of a family with a rich primary
    # must never be eligible as someone else's container.
    families = _families_for(EXAMPLES_DIR / "bancodobrasil.html", max_clusters=25)
    family = _transaction_family(families)
    assert family is not None, "the transaction family must survive, not be deleted via container absorption"
    assert any(m.cluster.content_signature == ("TEXT", "TEXT", "TEXT", "TEXT") for m in family.members)
