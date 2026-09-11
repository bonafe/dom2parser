"""Fase 1b: collapse exact-duplicate subtrees (byte-for-byte, ignoring the
`tail` text) into a single kept instance plus a lightweight reference
marking how many times it occurred.

This is orthogonal to cluster.siblings (Fase 4), which groups structurally
similar siblings that have *varying* text content. Here there is no
variation at all -- e.g. the same inline share-icon SVG repeated once per
article card. In the example corpus this is already mostly handled by
`strip.strip_tags` removing all <svg> outright, but the mechanism is kept
general: any other repeated decorative widget (a fixed badge, a fixed
icon built from nested <i>/<span>) benefits the same way.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from lxml import etree

from ..anchor import UID_ATTR

DEFAULT_MIN_SERIALIZED_LEN = 40
# Deliberately high: a byte-identical subtree can be a real data record with
# constant content (e.g. 28 identical "Acessar o recurso" download buttons in
# acervodadostecnicosgovbr.html, or empty `<td class="tituloLancamento">`
# spacer cells in bancodobrasil.html -- both legitimate repeated records that
# cluster/siblings (Fase E) must still see, not decoration to prune here).
# Genuine decorative duplication (e.g. one icon per article) tends to occur
# at a much larger scale than typical record counts on a single page; 50 is
# set above every example's real content-record count (max observed: 100
# newslist items in folhadesp.html, which are NOT byte-identical to each
# other since each headline differs) while still catching pathological
# decorative bloat if it were ever to reach this stage.
DEFAULT_MIN_COUNT = 50


def _serialize(el: etree._Element) -> bytes:
    """Serialize a subtree for hashing, ignoring `anchor.UID_ATTR`.

    That attribute is unique per element by construction, so leaving it in
    would make every subtree unique and silently reduce this stage to a
    no-op (measured on folhadesp.html: 1520 removed elements -> 0)."""
    stamped = [(d, d.attrib.pop(UID_ATTR)) for d in el.iter(etree.Element) if UID_ATTR in d.attrib]
    try:
        return etree.tostring(el, method="html", with_tail=False)
    finally:
        for d, uid in stamped:
            d.set(UID_ATTR, uid)


def dedup_identical_subtrees(
    root: etree._Element,
    min_len: int = DEFAULT_MIN_SERIALIZED_LEN,
    min_count: int = DEFAULT_MIN_COUNT,
) -> int:
    """Mutates root in place. Returns the number of elements removed."""
    hash_and_len: dict[etree._Element, tuple[str, int]] = {}
    for el in root.iter(etree.Element):
        data = _serialize(el)
        hash_and_len[el] = (hashlib.sha1(data).hexdigest(), len(data))

    groups: dict[str, list[etree._Element]] = defaultdict(list)
    for el, (digest, length) in hash_and_len.items():
        if length >= min_len:
            groups[digest].append(el)

    removed_count = 0
    removed: set[etree._Element] = set()
    for digest, elements in groups.items():
        if len(elements) < min_count:
            continue
        first, *rest = elements
        for el in rest:
            if el in removed:
                continue
            parent = el.getparent()
            if parent is None:
                continue
            placeholder = etree.Element("template-ref")
            tag = el.tag if isinstance(el.tag, str) else "node"
            placeholder.set("tag", tag)
            placeholder.set("dedup-hash", digest[:8])
            placeholder.tail = el.tail
            parent.replace(el, placeholder)
            removed.add(el)
            removed_count += 1
        if elements:
            first.set("data-dedup-count", str(len(elements)))

    return removed_count
