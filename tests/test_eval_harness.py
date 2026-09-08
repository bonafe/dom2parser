"""Fase F: the project's main regression suite. For each of the 6 real
examples, the cluster(s) annotated as "relevant" in ground_truth.yaml must
rank above the known dominant "noise" cluster(s) -- despite the noise
often being far larger or more repeated (146 menu items vs. 33 relevant
cells in bancodobrasil.html; 1490 filter options vs. 10 result cards in
conjuntodadosgovbr.html; 497 mega-menu items vs. 12 rows in
dadosabertrosfiocruz.html).

Uses the basic sanitizer only (see eval/harness.py docstring), so this
tests the ranking heuristic itself rather than sanitize.boilerplate's
denylist coverage (already tested in test_sanitize.py).
"""

from pathlib import Path

import pytest
import yaml

from dom2parser.html_io import load_html_file
from dom2parser.eval.harness import check_ranking

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
GROUND_TRUTH = yaml.safe_load((Path(__file__).parent / "fixtures" / "ground_truth.yaml").read_text())

# Generous absolute bound: the relevant cluster doesn't need to be #1
# overall (other small legitimate clusters may score similarly), just
# clearly near the top rather than buried among hundreds of candidates.
MAX_ACCEPTABLE_ABSOLUTE_RANK = 10


@pytest.mark.parametrize("entry", GROUND_TRUTH, ids=lambda e: e["file"])
def test_relevant_cluster_ranks_above_dominant_noise(entry):
    root = load_html_file(EXAMPLES_DIR / entry["file"])
    result = check_ranking(root, entry)

    assert result.relevant_best_rank is not None, f"{entry['file']}: no cluster matched the relevant selector(s)"
    assert result.relevant_best_rank <= MAX_ACCEPTABLE_ABSOLUTE_RANK, (
        f"{entry['file']}: relevant cluster ranked #{result.relevant_best_rank}, "
        f"expected top {MAX_ACCEPTABLE_ABSOLUTE_RANK}"
    )
    assert result.passed, (
        f"{entry['file']}: relevant cluster ranked #{result.relevant_best_rank}, "
        f"but noise cluster ranked #{result.noise_best_rank} (noise must rank lower)"
    )
