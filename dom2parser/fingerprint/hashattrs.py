"""Classify attributes/classes as safe identity signals vs. build/compiler
noise that must not be used to distinguish or group elements.

Two concrete, empirically-observed patterns drive this module:

1. Vue's scoped-CSS marker: every node of a compiled component gets an
   attribute NAME like `data-v-444d5111=""` -- the hash lives in the
   *attribute name*, and its value is constant (usually empty) everywhere
   that name occurs. This is compiler output, not semantic identity, but
   because it's uniform per component it's harmless to ignore rather than
   actively misleading. See acervodadostecnicosgovbr.html (470 occurrences
   of the same name).

2. Atomic/utility CSS (Stylex, CSS-in-JS, Tailwind-esque generators):
   `class="x78zum5 x1n2onr6 xh8yej3 ..."` -- individual class tokens with
   no semantic meaning. Unlike (1) they're ordinary `class` attribute
   values, not a special naming scheme, so they're filtered token-by-token
   using a string-shape heuristic instead of a document-wide constancy
   check. See oss_gov_br_whatsapp.html.

The class-token heuristic is inherently approximate (documented risk in
the project plan): short, vowel-poor, digit-bearing class names are
flagged even when a real one exists (e.g. bancodobrasil.html's "w100pct").
The cost of that false positive is bounded, though, because fingerprinting
(structural.py) falls back to other signals (data-testid, role, other
co-occurring classes, tag+shape) when a class is filtered out here.
"""

from __future__ import annotations

import re
from collections import defaultdict

from lxml import etree

VUE_SCOPED_CSS_ATTR_RE = re.compile(r"^data-v-[0-9a-f]{6,}$", re.IGNORECASE)


def looks_like_build_hash_attr_name(name: str) -> bool:
    return bool(VUE_SCOPED_CSS_ATTR_RE.match(name))


def find_uniform_build_artifact_attrs(root: etree._Element) -> frozenset[str]:
    """Scan the whole document for attribute NAMES matching a known
    build-hash naming convention (currently: Vue scoped CSS). Returns the
    set of attribute names that are safe to drop from fingerprinting
    because their value is constant everywhere they appear (uniform
    build/compiler artifact, not per-instance randomness)."""
    values_by_name: dict[str, set[str]] = defaultdict(set)
    for el in root.iter(etree.Element):
        for name, value in el.attrib.items():
            if looks_like_build_hash_attr_name(name):
                values_by_name[name].add(value)
    return frozenset(name for name, values in values_by_name.items() if len(values) <= 1)


_ATOMIC_CLASS_TOKEN_RE = re.compile(r"^[a-z][a-z0-9]*$")
_STYLEX_CLASS_TOKEN_RE = re.compile(r"^x[a-z0-9]{5,8}$")
# React renders `className={cond && "foo"}` as the literal string "false";
# such tokens are template bugs, never identity.
_JUNK_CLASS_TOKENS = frozenset({"false", "true", "null", "undefined"})


def looks_like_atomic_class_token(token: str) -> bool:
    """True for class tokens shaped like generated utility/atomic CSS
    classes (Stylex-style `x78zum5`) rather than semantic BEM/plain class
    names. Requires: all-lowercase-alnum (no hyphen/underscore/camelCase --
    those are strong signals of an intentional, human-written name), a
    length in the range generators typically produce, at least one digit,
    and very few vowels (generated identifiers rarely spell real words).

    Stylex specifically emits `x` + a 5-8 char base-36 hash, and that hash
    is frequently digit-free or vowel-rich (`xeuugli`, `xelbjmh`, `xahtqtb`
    on oss_gov_br_whatsapp.html), so that exact shape is accepted without
    the digit/vowel checks. Known cost: a real class like `xlarge` is
    flagged too -- bounded, since fingerprinting falls back to co-occurring
    classes or other signals."""
    if token in _JUNK_CLASS_TOKENS:
        return True
    if _STYLEX_CLASS_TOKEN_RE.match(token):
        return True
    if not (4 <= len(token) <= 12):
        return False
    if not _ATOMIC_CLASS_TOKEN_RE.match(token):
        return False
    if not any(c.isdigit() for c in token):
        return False
    vowels = sum(1 for c in token if c in "aeiou")
    return vowels <= 1


_RANDOM_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{6,}$")


def looks_like_random_token(token: str) -> bool:
    """True for id/testid VALUES shaped like a generated instance key
    (`Xk9pQ2`, `a8Bc3dEf`): separator-free alnum of generator-typical
    length mixing letters and digits. Deliberately loose on its own -- the
    caller only consults it once it already knows the value differs
    between same-tag siblings with no shared prefix, i.e. when the only
    remaining question is "random key or genuinely distinct names?"."""
    return bool(
        _RANDOM_TOKEN_RE.match(token)
        and any(c.isdigit() for c in token)
        and any(c.isalpha() for c in token)
    )


_STATE_CLASS_PREFIX_RE = re.compile(r"^(is|has|js)-[a-z0-9-]+$", re.IGNORECASE)
_STATE_CLASS_WORDS = frozenset(
    {
        "active",
        "collapsed",
        "current",
        "disabled",
        "expanded",
        "hidden",
        "open",
        "selected",
        "visible",
    }
)


def looks_like_state_class_token(token: str) -> bool:
    """True for a class that records an element's transient UI STATE rather
    than what the element is: `is-hidden`, `has-error`, `js-toggle`,
    `active`, `open`.

    State is not identity. Two elements of the same kind, one currently
    hidden, are still the same kind -- but including the state token in the
    fingerprint splits them into unrelated families. Measured on
    folhadesp.html: the 100 newslist headlines split into 70 `is-hidden`
    plus 30 others, so no single family (and therefore no single record
    selector) covered the page's main content. The split is visible in the
    path too, since both fingerprinting and `compact.paths` funnel through
    `semantic_class_tokens`.

    Known cost, symmetric with `looks_like_atomic_class_token`: a real
    content class that happens to be one of these words (a tab genuinely
    named `current`) stops being an identity signal. Bounded, since
    identity then falls back to the element's other classes."""
    lowered = token.lower()
    return lowered in _STATE_CLASS_WORDS or bool(_STATE_CLASS_PREFIX_RE.match(token))


def discriminating_class_tokens(class_attr_value: str) -> tuple[str, ...]:
    """Tokens usable to tell two groups of elements APART, which is not the
    same question as what an element is.

    A state class is deliberately excluded from identity (see
    `looks_like_state_class_token`) precisely because two elements that
    differ only by it are the same kind of thing. But that makes it the
    ideal thing to *subtract* with when one group has it and the other does
    not -- `li.item:not(.is-hidden)`. Only generated-looking tokens are
    dropped here, since those discriminate nothing."""
    tokens = (class_attr_value or "").split()
    return tuple(sorted(t for t in tokens if t and not looks_like_atomic_class_token(t)))


_UTILITY_CLASS_PREFIX_RE = re.compile(
    r"^(?:col|offset|order|g|gx|gy|row-cols"
    r"|m|mt|mb|ml|mr|mx|my|ms|me|p|pt|pb|pl|pr|px|py|ps|pe|gap|space|margin|padding"
    r"|w|h|min-w|min-h|max-w|max-h|maxw|minw|display"
    r"|d|flex|grid|justify|align|items|content|self|place|order|v-align"
    r"|text|font|leading|tracking|whitespace|truncate|lh|color|link"
    r"|float|position|top|bottom|start|end|inset|z|overflow|wb"
    r"|border|rounded|shadow|bg|opacity|ring|outline|anim|tmp"
    r"|sm|md|lg|xl|xxl)(?:-|--)[a-z0-9.-]+$"
)
# Primer's type scale (`f1`..`f6`) and nothing else of that shape.
_UTILITY_CLASS_SCALE_RE = re.compile(r"^f[1-6]$")
_UTILITY_CLASS_WORDS = frozenset(
    {
        "row", "container", "container-fluid", "clearfix", "flex", "grid",
        "block", "inline", "inline-block", "border", "rounded", "no-underline",
        "truncate", "unstyled", "wrap", "nowrap",
    }
)


def looks_like_utility_class_token(token: str) -> bool:
    """True for a Bootstrap/Tailwind/Primer-style LAYOUT class: `col-md-3`,
    `mb-5`, `bg-white`, `lh-condensed`, `color-fg-muted`, `no-underline`,
    `rounded`, `row`, `f3`.

    A utility class says where the box sits and how it is painted, never
    what it is -- every card on books.toscrape.com is wrapped in a
    `li.col-xs-6.col-sm-4.col-md-3`, and treating that as identity made the
    bare `li` outrank `article.product_pod` as the record. It is equally
    bad as a name: GitHub's topic cards produced fields called
    `no_underline`, `rounded` and `color_fg_muted`. And it makes a
    selector that survives exactly until the next spacing tweak --
    `div.my-2` reached the ten CKAN result cards precisely.

    **This is a word list on purpose.** The obvious structural rule --
    "a utility class is sprayed across many tags and contexts, a semantic
    one marks one kind of element in one place" -- was measured across the
    whole corpus and does not hold: `no-underline` appears 41 times on one
    tag under one parent, and `toctree-l1` appears 40 times on one tag
    under one parent. There is no signal in the document to separate them;
    the difference is that one vocabulary is published by a CSS framework
    and the other is the page author's. So the list is lexical, bounded,
    and wrong at the edges, exactly like `looks_like_atomic_class_token`.
    Do not spend another afternoon looking for the structural version.

    Bare `text` and `flex` are handled apart: `span.text` on
    quotes.toscrape.com is a real content class, so only the hyphenated
    `text-*` forms are utilities, while `flex` alone is layout."""
    lowered = token.lower()
    return (
        lowered in _UTILITY_CLASS_WORDS
        or bool(_UTILITY_CLASS_SCALE_RE.match(lowered))
        or bool(_UTILITY_CLASS_PREFIX_RE.match(lowered))
    )


def semantic_class_tokens(class_attr_value: str) -> tuple[str, ...]:
    """The subset of a `class` attribute's tokens considered safe identity
    signals: real class names that are neither generated-looking, nor a
    record of transient UI state, nor a layout utility -- order-independent."""
    tokens = (class_attr_value or "").split()
    return tuple(
        sorted(
            t
            for t in tokens
            if t
            and not looks_like_atomic_class_token(t)
            and not looks_like_state_class_token(t)
            and not looks_like_utility_class_token(t)
        )
    )
