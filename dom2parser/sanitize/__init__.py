"""Fase B: the full sanitization pipeline, composing the individual steps
in the order that makes each one correct:

1. strip.sanitize   -- remove script/style/svg/noscript/meta/link/comments,
                        truncate data: URIs (Fase 1, basic).
2. boilerplate       -- remove nav/menu/sidebar/breadcrumb subtrees, and
                        anything hidden via inline `display:none`
                        (must run BEFORE attrs strips the `style` attribute
                        that this check depends on).
3. attrs             -- strip noisy attributes (style, event handlers,
                        legacy visual attributes).
4. dedup_subtree     -- collapse exact-duplicate subtrees (Fase 1b).
"""

from __future__ import annotations

from lxml import etree

from . import attrs, boilerplate, dedup_subtree, strip


def full_sanitize(root: etree._Element) -> etree._Element:
    clean = strip.sanitize(root)
    boilerplate.strip_navigation(clean)
    boilerplate.strip_hidden_by_inline_style(clean)
    attrs.strip_noisy_attrs(clean)
    dedup_subtree.dedup_identical_subtrees(clean)
    return clean
