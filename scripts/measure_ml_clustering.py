"""Spike: does unsupervised clustering find records that the exact
fingerprint grouping in `cluster.siblings` misses?

Disposable script -- not part of the library's public API. Run with:
    .venv/bin/python scripts/measure_ml_clustering.py

The question comes from the literature. U-REST (WWW 2007) formalizes
record extraction as two stages -- cluster structurally similar regions,
then rank the groups -- which is exactly `cluster/siblings.py` followed by
`cluster/rank.py`. The difference is the kernel: the published systems use
a *distance* (tree edit distance is among U-REST's best features) where
this project uses equality of `fingerprint_key`. Miao et al. (WWW 2009)
turn the matrix the other way round: one row per distinct tag path, the
columns being where that path occurs in the document.

So two variants are measured against the exact grouping, on the committed
`corpus/` only (`examples/` is gitignored, so results there would not be
reproducible):

  A  one row per candidate element; TF-IDF over a bag of path n-grams,
     class tokens, attribute names, child tags, depth and content
     signature; cosine + agglomerative average linkage.
  B  one row per distinct tag path; binary occurrence vector over document
     positions (Miao's "visual signal"); cosine + agglomerative.

Both are given an ORACLE threshold: the script sweeps the linkage
threshold and keeps whichever value scores best *against the ground
truth*, which no real deployment could do. That is deliberate -- it makes
the comparison an upper bound, so a loss is conclusive while a win still
has to be paid for with a threshold nobody knows how to pick.

Variant B caveat: Miao's output is a data *region*, a set of co-occurring
paths, not a record element set. Mapping it back is approximate, so B is
scored generously -- over each path's own element set AND over each
cluster's union -- taking whichever reading does better.

RESULT (2026-09-11, scikit-learn 1.9.1, numpy 2.5.3, 11 corpus pages):

  exact ground-truth element set recovered / mean best-F1

      full pipeline (shipped)        11 / 11    1.000
      grouping stage alone            5 / 11    0.886
      variant A (oracle threshold)    9 / 11    0.995
      variant B (oracle threshold)    7 / 11    0.915

  Read those four lines in the right order, because the interesting
  finding is not the one the question expected.

  1. The exact fingerprint grouping DOES fragment records. On its own it
     recovers 5 of 11, and where it fails it fails badly:
     wikipedia_olympics.html's best group is 15 elements against a
     ground truth of 65 (rowspan plus Parsoid's generated ids),
     wikipedia_countries_by_population.html's is 129 against 242. So the
     premise behind the question was right -- there is fragmentation.

  2. It does not matter, because the repair is already downstream. The
     shipped pipeline recovers 11 of 11. `cluster.families`,
     `select_top_level_clusters` and record segmentation are not
     polish -- they carry the run from 5/11 to 11/11, which is the first
     time that has been measured. Their docstrings say they exist to fix
     up `cluster_siblings` output; this is how much fixing up.

  3. A distance kernel is a genuine alternative route to part of that
     repair, and it is a worse one. Variant A beats the grouping stage
     on 6 pages, but it never beat the full pipeline on ANY page, and
     the oracle flatters it: held at one fixed threshold the best it
     reaches is 8/11 (t=0.3: 0.972, t=0.4: 0.976), against 11/11 for
     what ships. The oracle picks 0.05 for 5 pages, 0.15 for 2, 0.2 for
     2, 0.3 and 0.4 for one each -- so the per-page threshold is not a
     detail to tune away, it is the difference between 9/11 and 8/11,
     and only the ground truth can supply it.

  4. Variant B (Miao's orientation) is the weakest at 7/11, and fails
     where a tag path is not enough to say what an element is: it cannot
     see `class`, so hackernews_front.html scores 0.488 (best group 93
     against a gold of 30) and datagov_datasets.html 0.667 (40 against
     20). Both are pages where the distinguishing signal is a class name
     that the path does not carry.

  Determinism: two consecutive runs produce byte-identical output, so
  the instability here is across pages, not across runs.

DECISION: NOT adopted. Nothing in either variant beats the shipped
pipeline on any of the 11 pages, so there is no gap to close. Adopting a
distance kernel would mean numpy + scikit-learn on the main path, a
threshold where the pipeline currently has no hyperparameter at all, and
losing the property that every grouping decision traces to a documented
rule -- in exchange for a stage-level improvement that the existing
downstream repair already delivers, and delivers further.

What the literature does justify is the *architecture*: U-REST's two
stages are `cluster/siblings.py` then `cluster/rank.py`, and that shape
is confirmed rather than challenged. `cluster.siblings.cluster_siblings`
stays as it is.

Re-run this script before revisiting the question. The decision rests on
the shipped pipeline scoring 11/11; if `_KNOWN_GAPS` in
tests/test_corpus.py ever gains a clustering-shaped entry, that premise
no longer holds and variant A at a fixed threshold is the first thing to
re-measure.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import yaml
from lxml import etree
from lxml.cssselect import CSSSelector
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer

from dom2parser.anchor import UID_ATTR, stamp_uids
from dom2parser.cluster.siblings import cluster_siblings, content_signature_sequence
from dom2parser.fingerprint.hashattrs import semantic_class_tokens
from dom2parser.fingerprint.structural import (
    filter_meaningful_candidates,
    generated_ids,
    reused_ids,
)
from dom2parser.html_io import parse_html
from dom2parser.parser.build import build_spec
from dom2parser.sanitize.strip import sanitize as basic_sanitize

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

# Same floor the ranking harness uses -- a "cluster" of one is not a
# repeated structure (eval/harness.py:26).
MIN_CLUSTER_SIZE = 2

# Agglomerative linkage needs an n x n distance matrix; at 8000 elements
# that is already ~500MB in float64. Pages above this are reported as
# skipped rather than silently sampled, since sampling would make the
# exact-set-match check meaningless.
MAX_UNIVERSE = 8000

# The oracle sweep. Cosine distance is in [0, 2] but everything of
# interest here lives below 1.
THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.85]


# ---------------------------------------------------------------- features


def _tag_path(el: etree._Element) -> tuple[str, ...]:
    path = []
    node = el
    while node is not None and isinstance(node.tag, str):
        path.append(node.tag)
        node = node.getparent()
    return tuple(reversed(path))


def element_features(el: etree._Element, gen_ids: frozenset[str], doc_ids: frozenset[str]) -> str:
    """The bag of features for variant A, as a whitespace-joined string for
    TfidfVectorizer. Mirrors the signals `fingerprint.structural` uses,
    plus the path and depth context a distance-based method is supposed to
    be able to exploit and exact matching cannot."""
    path = _tag_path(el)
    tokens = [f"tag:{el.tag}", f"depth:{len(path) // 3}"]

    for n in (2, 3, 4):
        if len(path) >= n:
            tokens.append("path%d:%s" % (n, "/".join(path[-n:])))

    child_tags = [c.tag for c in el if isinstance(c.tag, str)]
    tokens += [f"kid:{t}" for t in child_tags]
    tokens.append("kids:%s" % "/".join(sorted(child_tags)))

    tokens += [f"cls:{t}" for t in semantic_class_tokens(el.get("class", ""))]

    for name, value in el.attrib.items():
        if name == UID_ATTR:
            continue
        tokens.append(f"attr:{name}")
        if name in ("data-testid", "role") or name.startswith("aria-"):
            tokens.append(f"{name}={value}")

    # Same rule as structural.py: an id is identity only when reused, and
    # never when a template engine minted it.
    el_id = el.get("id")
    if el_id and el_id in doc_ids and el_id not in gen_ids:
        tokens.append(f"id:{el_id}")

    signature = content_signature_sequence(el)
    tokens.append("sig:%s" % "|".join(signature))
    tokens += [f"sigpos:{i}:{t}" for i, t in enumerate(signature)]

    return " ".join(tokens)


# ----------------------------------------------------------------- scoring


@dataclass
class Score:
    exact: bool
    best_f1: float
    n_groups: int
    detail: str = ""


def score_partition(groups: list[set[str]], gold: set[str]) -> Score:
    """`groups` are UID sets. Exact match is the criterion that actually
    matters -- it is what tests/test_corpus.py:86 asserts. best-F1 is the
    "how close did it get" fallback, which distinguishes a shattered
    record from one merged with its neighbours."""
    exact = any(g == gold for g in groups)
    best_f1, best_group = 0.0, None
    for g in groups:
        if not g:
            continue
        hit = len(g & gold)
        if not hit:
            continue
        precision = hit / len(g)
        recall = hit / len(gold)
        f1 = 2 * precision * recall / (precision + recall)
        if f1 > best_f1:
            best_f1, best_group = f1, g
    detail = ""
    if best_group is not None and not exact:
        detail = f"best group {len(best_group)} vs gold {len(gold)}"
    return Score(exact=exact, best_f1=best_f1, n_groups=len(groups), detail=detail)


def _agglomerative(matrix, threshold: float) -> np.ndarray:
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="cosine",
        linkage="average",
    )
    return model.fit_predict(matrix)


def _groups_from_labels(labels, uids: list[str]) -> list[set[str]]:
    groups: dict[int, set[str]] = {}
    for label, uid in zip(labels, uids):
        groups.setdefault(label, set()).add(uid)
    return [g for g in groups.values() if len(g) >= MIN_CLUSTER_SIZE]


def sweep(build_groups, gold: set[str]) -> tuple[Score, float, dict[float, Score]]:
    """Best score over the threshold sweep, the threshold that got it, and
    every threshold's score.

    The best-of is the ORACLE: it reads the ground truth to pick a
    hyperparameter, which no deployment could do, so it is an upper bound
    rather than a usable system. The per-threshold dict is what answers
    the question the oracle hides -- whether one FIXED threshold works
    across pages.
    """
    best, best_threshold = Score(False, 0.0, 0), None
    per_threshold: dict[float, Score] = {}
    for threshold in THRESHOLDS:
        score = build_groups(threshold)
        if score is None:
            continue
        per_threshold[threshold] = score
        if (score.exact, score.best_f1) > (best.exact, best.best_f1):
            best, best_threshold = score, threshold
    return best, best_threshold, per_threshold


# ---------------------------------------------------------------- variants


def variant_a(dense, uids: list[str], gold: set[str]):
    return sweep(
        lambda t: score_partition(_groups_from_labels(_agglomerative(dense, t), uids), gold),
        gold,
    )


def pipeline_score(html: str, root: etree._Element, gold_all: set[str]) -> Score:
    """What the FULL pipeline emits, not just the clustering stage.

    This is the fair baseline, and the reason it has to be here: several
    later stages (`cluster.families`, `select_top_level_clusters`, record
    segmentation) exist specifically to repair `cluster_siblings`' output,
    so scoring the raw clustering stage alone understates the shipped
    system. Uses the same accept rule as tests/test_corpus.py -- an exact
    element set, or a wrapper holding exactly one ground-truth element
    each."""
    groups = []
    for record in build_spec(html).records:
        got = {el.get(UID_ATTR) for el in CSSSelector(record.selector)(root)}
        groups.append(got)
        if len(got) == len(gold_all):
            # 1:1 wrapper (test_corpus.py:53): data.gov nests the record in
            # a `li` that is equally defensible as "the record".
            by_uid = {uid: el for el in root.iter() if (uid := el.get(UID_ATTR)) in got}
            covered = set()
            for el in by_uid.values():
                inside = {uid for d in el.iter() if (uid := d.get(UID_ATTR)) in gold_all}
                if len(inside) != 1:
                    break
                covered |= inside
            else:
                if covered == gold_all:
                    groups.append(set(gold_all))
    return score_partition(groups, gold_all)


def variant_b(candidates: list, uids: list[str], gold: set[str]):
    """Miao's orientation: cluster tag paths by where they occur.

    Scored generously (see the module docstring): the candidate groups are
    every path's own element set plus every cluster's union, because a
    path cluster is a data region, not a record set."""
    by_path: dict[tuple[str, ...], list[str]] = {}
    for el, uid in zip(candidates, uids):
        by_path.setdefault(_tag_path(el), []).append(uid)

    paths = sorted(by_path)
    if len(paths) < 2:
        return Score(False, 0.0, 0), None

    position = {uid: i for i, uid in enumerate(uids)}
    occurrence = np.zeros((len(paths), len(uids)), dtype=np.float64)
    for row, path in enumerate(paths):
        for uid in by_path[path]:
            occurrence[row, position[uid]] = 1.0

    # The null model: grouping by tag path with no clustering at all.
    path_groups = [set(by_path[p]) for p in paths]

    def build(threshold: float):
        labels = _agglomerative(occurrence, threshold)
        unions: dict[int, set[str]] = {}
        for label, path in zip(labels, paths):
            unions.setdefault(label, set()).update(by_path[path])
        groups = path_groups + [g for g in unions.values() if len(g) >= MIN_CLUSTER_SIZE]
        return score_partition(groups, gold)

    return sweep(build, gold)


# -------------------------------------------------------------------- main


def measure(entry: dict) -> dict:
    html = (CORPUS_DIR / entry["file"]).read_text(errors="replace")
    root = stamp_uids(parse_html(html))

    gold_all = {el.get(UID_ATTR) for el in CSSSelector(entry["record"]["selector"])(root)}

    clean = basic_sanitize(root)
    doc_ids = reused_ids(clean)
    gen_ids = generated_ids(clean)
    candidates = filter_meaningful_candidates(list(clean.iter(etree.Element)), doc_ids)
    uids = [el.get(UID_ATTR) for el in candidates]

    universe = set(uids)
    gold = gold_all & universe

    row = {
        "file": entry["file"],
        "universe": len(universe),
        "gold": len(gold_all),
        "gold_in_universe": len(gold),
    }

    row["pipeline"] = pipeline_score(html, root, gold_all)

    if not gold:
        row["note"] = "ground-truth elements are not in the candidate set"
        return row

    current = [
        {el.get(UID_ATTR) for el in c.elements}
        for c in cluster_siblings(candidates, doc_ids)
        if c.count >= MIN_CLUSTER_SIZE
    ]
    row["current"] = score_partition(current, gold)

    if len(universe) > MAX_UNIVERSE:
        row["note"] = f"skipped A/B: {len(universe)} candidates over the {MAX_UNIVERSE} cap"
        return row

    corpus = [element_features(el, gen_ids, doc_ids) for el in candidates]
    dense = TfidfVectorizer(analyzer=str.split, min_df=1).fit_transform(corpus).toarray()

    row["a"], row["a_threshold"], row["a_per_threshold"] = variant_a(dense, uids, gold)
    row["b"], row["b_threshold"], _ = variant_b(candidates, uids, gold)
    return row


def _cell(score: Score | None) -> str:
    if score is None:
        return "        -"
    return f"{'EXACT' if score.exact else '     '} {score.best_f1:5.3f}"


def main() -> int:
    entries = yaml.safe_load((CORPUS_DIR / "ground_truth.yaml").read_text())

    header = (
        f"{'page':<42} {'cand':>5} {'gold':>5}   {'pipeline':<12} {'grouping':<12} "
        f"{'A (oracle)':<12} {'B (oracle)':<12} thresholds"
    )
    print(header)
    print("-" * len(header))

    rows = []
    for entry in entries:
        row = measure(entry)
        rows.append(row)
        thresholds = ""
        if row.get("a_threshold") is not None or row.get("b_threshold") is not None:
            thresholds = f"A={row.get('a_threshold')} B={row.get('b_threshold')}"
        print(
            f"{row['file']:<42} {row['universe']:>5} {row['gold_in_universe']:>5}   "
            f"{_cell(row.get('pipeline')):<12} {_cell(row.get('current')):<12} "
            f"{_cell(row.get('a')):<12} {_cell(row.get('b')):<12} {thresholds}"
        )
        if row.get("note"):
            print(f"{'':<42} {row['note']}")
        for name in ("current", "a", "b"):
            score = row.get(name)
            if score is not None and score.detail:
                print(f"{'':<42} {name}: {score.detail}")

    print()
    labels = (
        ("pipeline", "full pipeline (shipped)"),
        ("current", "grouping stage alone"),
        ("a", "variant A (oracle threshold)"),
        ("b", "variant B (oracle threshold)"),
    )
    for name, label in labels:
        scored = [r[name] for r in rows if r.get(name) is not None]
        if not scored:
            continue
        exact = sum(1 for s in scored if s.exact)
        mean_f1 = sum(s.best_f1 for s in scored) / len(scored)
        print(f"{label:<30} exact {exact:>2} / {len(scored)}    mean best-F1 {mean_f1:.3f}")

    # The question the oracle hides: is there ONE threshold that works?
    print()
    print("variant A held at a FIXED threshold (no oracle):")
    per_page = [r["a_per_threshold"] for r in rows if r.get("a_per_threshold")]
    for threshold in THRESHOLDS:
        scored = [p[threshold] for p in per_page if threshold in p]
        if not scored:
            continue
        exact = sum(1 for s in scored if s.exact)
        mean_f1 = sum(s.best_f1 for s in scored) / len(scored)
        print(f"    t={threshold:<5} exact {exact:>2} / {len(scored)}    mean best-F1 {mean_f1:.3f}")

    for baseline, label in (("pipeline", "full pipeline"), ("current", "grouping stage")):
        won = [
            r["file"]
            for r in rows
            if r.get(baseline) is not None
            and any(
                r.get(v) is not None
                and (r[v].exact, r[v].best_f1) > (r[baseline].exact, r[baseline].best_f1)
                for v in ("a", "b")
            )
        ]
        print()
        print(f"pages where a variant beat the {label}:", ", ".join(won) if won else "none")

    spread = Counter(r.get("a_threshold") for r in rows if r.get("a_threshold") is not None)
    print("oracle thresholds chosen for A:", dict(sorted(spread.items(), key=lambda kv: kv[0] or 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
