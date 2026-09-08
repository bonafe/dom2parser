"""Human-readable ancestor-path descriptions for a cluster, e.g.
`div#fatura2 > div.lancamentos > table > tbody > tr`, used by both
renderers to show the LLM *where* a cluster lives in the document (the
spec's "Relevant DOM path").
"""

from __future__ import annotations

from ..fingerprint.hashattrs import semantic_class_tokens


def describe_element(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else "?"
    el_id = el.get("id")
    if el_id:
        return f"{tag}#{el_id}"
    testid = el.get("data-testid")
    if testid:
        return f'{tag}[data-testid="{testid}"]'
    classes = semantic_class_tokens(el.get("class", ""))
    if classes:
        return f"{tag}.{'.'.join(classes[:3])}"
    return tag


def describe_path(el, max_levels: int = 6) -> str:
    parts = []
    node = el
    while node is not None and len(parts) < max_levels:
        parts.append(describe_element(node))
        node = node.getparent()
    return " > ".join(reversed(parts))
