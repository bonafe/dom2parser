"""Small shared helpers for pulling text out of lxml elements, used by
clustering, outlier detection, and rendering alike."""

from __future__ import annotations


def full_text(el) -> str:
    return el.text_content() if hasattr(el, "text_content") else "".join(el.itertext())


def direct_children_text(el) -> list[str]:
    return [full_text(child) for child in el if isinstance(child.tag, str)]


def collapse_whitespace(text: str) -> str:
    return " ".join((text or "").split())
