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


def test_bancodobrasil_2_default_output_accounts_for_every_lancamentos_row():
    # End-to-end regression test for two bugs found reviewing this second
    # real fixture: (1) the dominant 140-row transaction pattern must stay
    # "primary" despite a 2-row content-classifier quirk making it look
    # momentarily "richer", and (2) every row under div.lancamentos must
    # be accounted for across the family's members (no silent drops from
    # a heterogeneous-cluster misattribution or an absorbed-container bug).
    html = (EXAMPLES_DIR / "bancodobrasil_2.html").read_text(encoding="utf-8")
    result = dom2parser.compress(html)

    family = next(
        entry for entry in result.json
        if "members" in entry and any(m["count"] == 140 for m in entry["members"])
    )
    assert family["container"] is not None
    primary = next(m for m in family["members"] if m["role"] == "primary")
    assert primary["count"] == 140
    assert primary["signature"] == ["DATE", "TEXT", "CURRENCY", "MONEY"]

    # 140 transactions + 11 section rows + 11 blank rows + 3 summary rows
    # + 2 misclassified-transaction variant + 2 header-row variant = 169
    # (the page's 170th row is a lone, uncounted anomaly below the
    # min-cluster-size-2 threshold).
    assert sum(m["count"] for m in family["members"]) == 169
