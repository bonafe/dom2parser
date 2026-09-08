"""Fase B: drop attributes that are known noise (inline styles, JS event
handlers, legacy purely-visual HTML attributes) while keeping everything
else -- including id/class/name/role/type/href/data-*/aria-*, which are
exactly the attributes later stages (fingerprinting) need to work with.

Deliberately a denylist, not an allowlist: real pages use attributes we
can't fully enumerate in advance (custom data-* conventions, ARIA states,
etc.), and it's safer to strip only attributes we're confident are noise
than to risk silently dropping something a later stage needed.
"""

from __future__ import annotations

import re

from lxml import etree

EVENT_HANDLER_RE = re.compile(r"^on[a-z]+$", re.IGNORECASE)

LEGACY_VISUAL_ATTRS = {
    "align",
    "valign",
    "bgcolor",
    "border",
    "cellpadding",
    "cellspacing",
    "hspace",
    "vspace",
    "marginwidth",
    "marginheight",
    "frameborder",
    "scrolling",
    "background",
    "link",
    "vlink",
    "alink",
    "topmargin",
    "leftmargin",
    "width",
    "height",
    "color",
    "face",
}

DENYLIST_EXACT = {"style"} | LEGACY_VISUAL_ATTRS


def strip_noisy_attrs(root: etree._Element) -> None:
    for el in root.iter(etree.Element):
        for name in list(el.attrib.keys()):
            lname = name.lower()
            if lname in DENYLIST_EXACT or EVENT_HANDLER_RE.match(lname):
                del el.attrib[name]
