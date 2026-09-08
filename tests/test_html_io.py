"""Fase 0: the 6 real-world examples load cleanly and the ground truth
selector counts actually match the raw documents."""

from pathlib import Path

import pytest
import yaml
from lxml.cssselect import CSSSelector

from dom2parser.html_io import describe, load_html_file

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
GROUND_TRUTH_PATH = Path(__file__).parent / "fixtures" / "ground_truth.yaml"


def load_ground_truth() -> list[dict]:
    return yaml.safe_load(GROUND_TRUTH_PATH.read_text())


EXAMPLE_FILES = sorted(p.name for p in EXAMPLES_DIR.glob("*.html"))


@pytest.mark.parametrize("filename", EXAMPLE_FILES)
def test_example_loads_without_exception(filename):
    root = load_html_file(EXAMPLES_DIR / filename)
    info = describe(root)
    assert info["tag_count"] > 0
    assert info["text_len"] > 0


@pytest.mark.parametrize("entry", load_ground_truth(), ids=lambda e: e["file"])
def test_ground_truth_selectors_match_raw_document(entry):
    """Sanity-check that the manually annotated selectors/counts in
    ground_truth.yaml still match the actual example file, so later phases
    can trust this fixture as a reliable regression oracle."""
    root = load_html_file(EXAMPLES_DIR / entry["file"])
    for group in ("relevant", "noise"):
        for item in entry.get(group, []):
            n = len(CSSSelector(item["selector"])(root))
            assert n == item["count"], (
                f"{entry['file']}: selector {item['selector']!r} expected "
                f"{item['count']} matches, found {n}"
            )
