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

CORPUS_DIR = Path(__file__).parent.parent / "corpus"
GROUND_TRUTH = yaml.safe_load((CORPUS_DIR / "ground_truth.yaml").read_text())

# (file, check) -> measured reason. Removing an entry is how a fix is
# claimed; a stale entry fails the suite because the xfail is strict.
_KNOWN_GAPS: dict[tuple[str, str], str] = {}


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


def _matching_record(entry):
    spec, root = _built(entry)
    expected = _uids(root, entry["record"]["selector"])
    for record in spec.records:
        if _uids(root, record.selector) == expected:
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
