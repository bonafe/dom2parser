"""Fase B: strip whole subtrees that are page infrastructure rather than
content -- navigation/menus/sidebars/breadcrumbs, and widgets that are
hidden-by-default (e.g. a closed filter dropdown).

These are *targeted* heuristics, not a general boilerplate remover: broad
keyword matching on nav-like classes has real false-positive risk (a
content section could legitimately use the word "menu"), so this module
only removes the outermost matching ancestor once, and only for a small,
empirically-justified set of signals (see examples/*.html findings in
tests/fixtures/ground_truth.yaml).
"""

from __future__ import annotations

import re

from lxml import etree

NAV_KEYWORDS = (
    "nav",
    "menu",
    "sidebar",
    "breadcrumb",
    "hamburger",
    "superfish",
    "sf-depth",
)
NAV_KEYWORD_RE = re.compile("|".join(re.escape(k) for k in NAV_KEYWORDS), re.IGNORECASE)

NAV_TAGS = {"nav"}
NAV_ROLES = {"navigation", "menu", "menubar", "menuitem"}

INLINE_DISPLAY_NONE_RE = re.compile(r"display\s*:\s*none", re.IGNORECASE)


def _looks_like_nav(el: etree._Element) -> bool:
    if el.tag in NAV_TAGS:
        return True
    role = el.get("role", "")
    if role.lower() in NAV_ROLES:
        return True
    haystack = f"{el.get('id', '')} {el.get('class', '')}"
    return bool(NAV_KEYWORD_RE.search(haystack))


def strip_navigation(root: etree._Element) -> None:
    """Remove the outermost element matching a nav-like signal, top-down,
    so a nested nav-like class inside an already-removed nav isn't visited
    twice (and doesn't matter if it were)."""
    to_remove = []
    # iterate depth-first from the root; once a match is found we don't
    # need to descend into it looking for nested matches.
    stack = [root]
    while stack:
        el = stack.pop()
        if el is root:
            stack.extend(reversed(el))
            continue
        if _looks_like_nav(el):
            to_remove.append(el)
            continue
        stack.extend(reversed(el))
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def strip_hidden_by_inline_style(root: etree._Element) -> None:
    """Remove elements that are hidden by an inline `display:none` -- e.g. a
    closed filter-dropdown panel rendered into the DOM but never shown.

    Deliberately does NOT touch the `hidden` boolean attribute or
    class-based hiding (e.g. `.is-hidden` in an external stylesheet):
    those are used by some sites (see folhadesp.html) for real,
    client-side-paginated content that must be kept.
    """
    to_remove = [
        el
        for el in root.iter(etree.Element)
        if INLINE_DISPLAY_NONE_RE.search(el.get("style", ""))
    ]
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
