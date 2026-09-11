"""End-to-end tests for the public `compress()` API and both renderers.

Also pins the schema-2 contract: one shape for every structure, with
`container` nullable rather than absent and `examples[].values` always an
object. Schema 1 had two shapes distinguished by which keys were present
and a `value` that was a string or a list depending on signature length,
so a consumer had to branch on both.
"""

from pathlib import Path

import dom2parser

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.html"))


def _structure_with_member_count(result, count):
    return next(
        s for s in result.json["structures"] if any(m["count"] == count for m in s["members"])
    )


def test_compress_runs_without_raising_on_every_example():
    assert EXAMPLE_FILES, "expected at least one fixture in examples/"
    for path in EXAMPLE_FILES:
        result = dom2parser.compress(path.read_text(encoding="utf-8", errors="ignore"))
        assert result.text.strip()
        assert result.json["schema_version"] == 2
        assert result.json["structures"]
        assert result.reduction["reduction_pct"]["tokens"] > 0


def test_every_structure_has_the_same_shape():
    """The point of schema 2: no consumer should have to ask which shape
    it got."""
    for path in EXAMPLE_FILES:
        result = dom2parser.compress(path.read_text(encoding="utf-8", errors="ignore"))
        for structure in result.json["structures"]:
            assert set(structure) == {
                "path_display",
                "record_selector",
                "container",
                "fields",
                "members",
            }, f"{path.name}: unexpected keys {sorted(structure)}"
            assert isinstance(structure["members"], list) and structure["members"]
            for member in structure["members"]:
                for example in member["examples"]:
                    assert isinstance(example["values"], dict), (
                        f"{path.name}: example values must always be an object, got "
                        f"{type(example['values']).__name__}"
                    )


def test_bancodobrasil_default_output_includes_the_section_role_rows():
    # Regression test: at the default max_clusters, the 12 category-header
    # rows used to be silently dropped from the output even though they
    # share their exact DOM shape with the page's single highest-ranked
    # cluster (the 122 transaction rows).
    result = dom2parser.compress((EXAMPLES_DIR / "bancodobrasil.html").read_text(encoding="utf-8"))
    assert "[section] count: 12" in result.text

    structure = _structure_with_member_count(result, 122)
    assert structure["container"] is not None
    assert any(m["role"] == "section" and m["count"] == 12 for m in structure["members"])


def test_bancodobrasil_2_default_output_accounts_for_every_lancamentos_row():
    # End-to-end regression test for two bugs found reviewing this second
    # real fixture: (1) the dominant 140-row transaction pattern must stay
    # "primary" despite a 2-row content-classifier quirk making it look
    # momentarily "richer", and (2) every row under div.lancamentos must
    # be accounted for across the family's members.
    result = dom2parser.compress((EXAMPLES_DIR / "bancodobrasil_2.html").read_text(encoding="utf-8"))

    structure = _structure_with_member_count(result, 140)
    assert structure["container"] is not None
    primary = next(m for m in structure["members"] if m["role"] == "primary")
    assert primary["count"] == 140
    assert primary["signature"] == ["DATE", "TEXT", "CURRENCY", "MONEY"]

    # 140 transactions + 11 section rows + 11 blank rows + 3 summary rows
    # + 2 misclassified-transaction variant + 2 header-row variant = 169
    # (the page's 170th row is a lone, uncounted anomaly below the
    # min-cluster-size-2 threshold).
    assert sum(m["count"] for m in structure["members"]) == 169


def test_compress_carries_a_verified_selector_and_named_fields():
    """The gap schema 2 exists to close: the output now addresses the
    records it describes, in the ORIGINAL document."""
    result = dom2parser.compress((EXAMPLES_DIR / "bancodobrasil.html").read_text(encoding="utf-8"))
    structure = _structure_with_member_count(result, 122)

    assert structure["record_selector"]["selector"] == "div.lancamentos tr"
    assert structure["record_selector"]["verified"]["recall"] == 1.0
    assert [f["name"] for f in structure["fields"]] == ["data", "transacoes", "moeda", "valor"]

    values = structure["members"][0]["examples"][0]["values"]
    assert set(values) == {"data", "transacoes", "moeda", "valor"}, (
        f"example values should be keyed by the derived field names, got {sorted(values)}"
    )


def test_compress_exposes_the_executable_parser():
    result = dom2parser.compress((EXAMPLES_DIR / "bancodobrasil.html").read_text(encoding="utf-8"))
    record = next(r for r in result.parser.records if r.selector == "div.lancamentos tr")
    assert [f.name for f in record.fields] == ["data", "transacoes", "moeda", "valor"]
    assert result.parser.to_yaml().startswith("schema_version:")
