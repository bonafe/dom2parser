"""Fase H: render selected families into the structured text format
sketched in the spec (`REPEATED STRUCTURE: ... x N`, `signature: ...`,
`examples: [...]`). A family with a single member and no linked container
renders exactly as the original flat block (path/count/signature/examples/
optional_fields); a family with several role variants and/or a linked
container renders as one nested block, so an LLM sees "this is one
repeated structure with these row types" instead of several unrelated
blocks that happen to share a DOM shape."""

from __future__ import annotations

from ..cluster.siblings import optional_fields
from ..dom_utils import collapse_whitespace, direct_children_text, full_text
from .paths import describe_path

MAX_FIELD_LEN = 200
MAX_TEXT_LEN = 300


def _example_repr(el, content_signature: tuple[str, ...]):
    if len(content_signature) > 1:
        return [collapse_whitespace(t)[:MAX_FIELD_LEN] for t in direct_children_text(el)]
    return collapse_whitespace(full_text(el))[:MAX_TEXT_LEN]


def _describe_field_key(key: tuple) -> str:
    tag, identity = key
    kind, value = identity
    if kind == "class":
        value = ".".join(value)
    return f"{tag}[{kind}={value}]"


def _member_body_lines(member, indent: str) -> list[str]:
    cluster = member.cluster
    lines = []
    if cluster.content_signature:
        lines.append(f"{indent}signature: {' | '.join(cluster.content_signature)}")

    lines.append(f"{indent}examples:")
    for i in member.sample.indices:
        el = cluster.elements[i]
        reasons = ",".join(member.sample.reasons.get(i, []))
        lines.append(f"{indent}  {_example_repr(el, cluster.content_signature)!r}  # {reasons}")

    opt = optional_fields(cluster)
    if opt:
        lines.append(f"{indent}optional_fields:")
        for key, count in opt.items():
            lines.append(f"{indent}  {_describe_field_key(key)}: present in {count}/{cluster.count}")
    return lines


def _record_lines(record) -> list[str]:
    """The verified selector and the named fields, shown above the
    structure they belong to. The `path` line below them is descriptive
    only -- it is truncated and `*`-masked, and is not a selector."""
    if record is None:
        return []
    lines = [
        f"  selector: {record.selector}"
        f"  # matches {record.verified['matched']}, covers all {record.verified['expected']}"
    ]
    if record.fields:
        lines.append("  fields:")
        for entry in record.fields:
            source = "" if entry.name_source == "header_row" else f" ({entry.name_source})"
            capture = f" @{entry.attribute}" if entry.attribute else ""
            presence = "" if entry.required else f", present in {entry.present}/{entry.total}"
            lines.append(
                f"    {entry.name}: {entry.locator}{capture}"
                f"  # {entry.type}{presence}{source}"
            )
    if record.skip_when.get("header_values"):
        lines.append(f"  skip header row: {record.skip_when['header_values']}")
    return lines


def render_family(family, record=None) -> str:
    path = describe_path(family.primary.cluster.elements[0]) if family.primary.cluster.elements else "?"
    lines = [path]
    lines.extend(_record_lines(record))
    if family.container_path is not None:
        lines.append(f"  container: {family.container_path} (count: {family.container_count})")
    lines.append("  row types:")
    for member in family.members:
        lines.append(f"    [{member.role}] count: {member.cluster.count}")
        lines.extend(_member_body_lines(member, "      "))
    return "\n".join(lines)


def render(families: list, by_family: dict | None = None, failures: list | None = None) -> str:
    by_family = by_family or {}
    blocks = ["REPEATED STRUCTURES (ranked by relevance):", ""]
    for position, family in enumerate(families):
        blocks.append(render_family(family, by_family.get(position)))
        blocks.append("")
    if failures:
        blocks.append(f"NO EXACT SELECTOR ({len(failures)} structures):")
        for failure in failures:
            closest = failure["near_misses"][0] if failure["near_misses"] else None
            if closest:
                blocks.append(
                    f"  {closest['selector']}  # matched {closest['matched']} for "
                    f"{closest['expected']} records (precision {closest['precision']})"
                )
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"
