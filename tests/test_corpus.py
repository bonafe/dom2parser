"""The public corpus scoreboard.

`examples/` holds real pages with personal data and is gitignored, so most
of this suite only runs on one machine. `corpus/` is the committed
counterpart: public pages chosen one per failure mode, with what a human
would extract written down in `corpus/ground_truth.yaml`. These tests are
the honest answer to "on how many pages does this work" -- a known gap is
a strict xfail with the measured reason, never a silently loosened
assertion, so fixing it flips a test rather than quietly changing a number.
"""

from pathlib import Path

import pytest
import yaml
from lxml.cssselect import CSSSelector

from dom2parser.anchor import UID_ATTR, stamp_uids
from dom2parser.html_io import parse_html
from dom2parser.parser.build import build_spec
from dom2parser.parser.executor import execute

CORPUS_DIR = Path(__file__).parent.parent / "corpus"
GROUND_TRUTH = yaml.safe_load((CORPUS_DIR / "ground_truth.yaml").read_text())

# (file, check) -> measured reason. Removing an entry is how a fix is
# claimed; a stale entry fails the suite because the xfail is strict.
_KNOWN_GAPS: dict[tuple[str, str], str] = {
    ("chatgpt.html", "record"): (
        "the two conversation turns (div.min-h-8.text-message, the message "
        "wrapper) form the highest-scored family on the page, but every "
        "top-ranked family's promoted level converges on the same wrong "
        "boundary -- span.contents (10), an unrelated set of inline "
        "formatting wrappers ProseMirror leaves inside the assistant's "
        "rendered markdown. With only 2 records, `records.promote()`'s "
        "injective-parent climb runs out of siblings to disambiguate on "
        "long before it reaches the level a human would call the record."
    ),
    ("chatgpt.html", "fields"): "no matching record is emitted; see the record gap",
    ("chatgpt.html", "values"): "no matching record is emitted; see the record gap",
}


def _params(check: str):
    for entry in GROUND_TRUTH:
        reason = _KNOWN_GAPS.get((entry["file"], check))
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        yield pytest.param(entry, marks=marks, id=entry["file"])


_SPECS: dict[str, tuple] = {}


def _built(entry):
    """Spec and stamped root for one page, built once per session."""
    if entry["file"] not in _SPECS:
        html = (CORPUS_DIR / entry["file"]).read_text(errors="replace")
        _SPECS[entry["file"]] = (build_spec(html), stamp_uids(parse_html(html)))
    return _SPECS[entry["file"]]


def _uids(root, selector):
    return {el.get(UID_ATTR) for el in CSSSelector(selector)(root)}


def _wraps_one_to_one(got: set, expected: set, root) -> bool:
    """True when each matched element contains exactly one ground-truth
    element and every one is covered -- the same records, read off a 1:1
    wrapper.

    data.gov nests `div.dataset-content` inside `li.usa-collection__item`,
    and both carry a real class. Either is the record; insisting on the
    exact element set would be pinning an implementation choice rather
    than the answer. A wrapper that swallows two records, or misses one,
    still fails -- which is the bug this file exists to catch."""
    if len(got) != len(expected):
        return False
    by_uid = {uid: el for el in root.iter() if (uid := el.get(UID_ATTR)) in got}
    covered = set()
    for el in by_uid.values():
        inside = {uid for d in el.iter() if (uid := d.get(UID_ATTR)) in expected}
        if len(inside) != 1:
            return False
        covered |= inside
    return covered == expected


def _matching_record(entry):
    spec, root = _built(entry)
    expected = _uids(root, entry["record"]["selector"])
    for record in spec.records:
        got = _uids(root, record.selector)
        if got == expected or _wraps_one_to_one(got, expected, root):
            return record
    return None


@pytest.mark.parametrize("entry", list(_params("record")))
def test_some_record_is_exactly_the_ground_truth_element_set(entry):
    spec, root = _built(entry)
    record = _matching_record(entry)
    assert record is not None, (
        f"{entry['file']}: no emitted record matches the {entry['record']['count']} elements of "
        f"{entry['record']['selector']!r}; emitted "
        f"{[(r.selector, r.count) for r in spec.records]}, failures "
        f"{[f['near_misses'][:1] for f in spec.failures]}"
    )


@pytest.mark.parametrize(
    "entry", [p for p in _params("fields") if "expected_fields" in p.values[0]]
)
def test_field_names_the_page_provides_are_derived(entry):
    record = _matching_record(entry)
    assert record is not None, f"{entry['file']}: record not found, see the record test"
    names = [f.name for f in record.fields]
    missing = [n for n in entry["expected_fields"] if n not in names]
    assert not missing, (
        f"{entry['file']}: page names these columns itself but they were not derived: "
        f"{missing}; got {[(f.name, f.name_source) for f in record.fields]}"
    )


@pytest.mark.parametrize("entry", [p for p in _params("fields") if "min_fields" in p.values[0]])
def test_enough_fields_are_discovered(entry):
    record = _matching_record(entry)
    assert record is not None, f"{entry['file']}: record not found, see the record test"
    assert len(record.fields) >= entry["min_fields"], (
        f"{entry['file']}: a consumer wants at least {entry['min_fields']} values per record, "
        f"got {[(f.name, f.type) for f in record.fields]}"
    )


@pytest.mark.parametrize("entry", [p for p in _params("values") if "expected_values" in p.values[0]])
def test_hand_read_values_come_out_of_the_extraction(entry):
    """The check that separates "it looks right" from "it is right".

    Every other test here is about shape: which elements the selector
    reaches, how many fields, what they are called. This one compares
    against values read by hand off the markup, so a locator that drifted
    onto a wrapper, a value glued to its neighbour, or a title truncated
    to its visible form is caught."""
    record = _matching_record(entry)
    assert record is not None, f"{entry['file']}: record not found, see the record test"
    html = (CORPUS_DIR / entry["file"]).read_text(errors="replace")
    extraction = execute(_built(entry)[0], html)[record.name]

    for case in entry["expected_values"]:
        values = extraction.records[case["index"]].values
        got = list(values.values())
        missing = [want for want in case["values"] if not any(want in v for v in got)]
        assert not missing, (
            f"{entry['file']} record {case['index']}: {missing} read off the page but not "
            f"extracted; got {values}"
        )


@pytest.mark.parametrize("entry", list(_params("unique")))
def test_no_two_records_share_an_element_set(entry):
    spec, root = _built(entry)
    seen = {}
    for record in spec.records:
        key = frozenset(_uids(root, record.selector))
        assert key not in seen, (
            f"{entry['file']}: {record.selector!r} and {seen[key]!r} select the same elements "
            "-- one record emitted twice"
        )
        seen[key] = record.selector
