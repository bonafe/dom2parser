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


def semantic_class_tokens(class_attr_value: str) -> tuple[str, ...]:
    """The subset of a `class` attribute's tokens considered safe identity
    signals: real class names that are neither generated-looking nor a
    record of transient UI state, order-independent."""
    tokens = (class_attr_value or "").split()
    return tuple(
        sorted(
            t
            for t in tokens
            if t and not looks_like_atomic_class_token(t) and not looks_like_state_class_token(t)
        )
    )
