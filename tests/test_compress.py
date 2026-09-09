"""End-to-end smoke tests for the public `compress()` API -- prior to this,
no test in the suite exercised `compress()` or either renderer directly.
"""

from pathlib import Path

import dom2parser

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.html"))


def test_compress_runs_without_raising_on_every_example():
    assert EXAMPLE_FILES, "expected at least one fixture in examples/"
    for path in EXAMPLE_FILES:
        html = path.read_text(encoding="utf-8", errors="ignore")
        result = dom2parser.compress(html)
        assert result.text.strip()
        assert isinstance(result.json, list) and result.json
        assert result.reduction["reduction_pct"]["tokens"] > 0


def test_bancodobrasil_default_output_includes_the_section_role_rows():
    # Regression test for the bug this feature fixes: at the default
    # max_clusters, the 12 category-header rows used to be silently
    # dropped from the output even though they share their exact DOM
    # shape with the page's single highest-ranked cluster (the 122
    # transaction rows).
    html = (EXAMPLES_DIR / "bancodobrasil.html").read_text(encoding="utf-8")
    result = dom2parser.compress(html)
    assert "[section] count: 12" in result.text

    family = next(
        entry for entry in result.json
        if "members" in entry and any(m["count"] == 122 for m in entry["members"])
    )
    assert family["container"] is not None
    assert any(m["role"] == "section" and m["count"] == 12 for m in family["members"])
