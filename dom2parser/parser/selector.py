"""Fase J: synthesize a CSS selector that finds a family's records in the
ORIGINAL document.

The compact representation's `path` cannot do this job: it is capped at 6
ancestor levels with no truncation marker, it carries `*` masks that are
by definition not literal, and it describes the sanitized tree, whose
ancestor chain differs wherever a nav/hidden subtree was deleted. What is
emitted here is instead *measured*: every candidate is run against the
original document and scored against the known target set, so the selector
that ships is one that was observed to work.

Recall must be 1.0: a record the selector cannot reach is a record the
parser will silently never return, so no candidate that misses one is
acceptable at any precision. Precision is measured and reported but not
required here -- `parser.build` decides what to do with an overshoot, and
refuses to emit a record whose overshoot nothing explains.

Candidates are generated liberally from properties shared by the whole
target set and then filtered by measurement, so a candidate does not need
to be provably correct to be worth trying.

Note the asymmetry between the two class-token helpers, which answer
different questions. Identity ("what is this element?") uses
`semantic_class_tokens`, which drops state classes. Discrimination ("what
separates these from those?") uses `discriminating_class_tokens`, which
keeps them -- a state class is worthless as identity and ideal as the
thing to subtract in `:not(...)`.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from functools import lru_cache

from lxml.cssselect import CSSSelector

from ..anchor import UID_ATTR
from ..compact.paths import _shared_prefix
from ..fingerprint.hashattrs import discriminating_class_tokens, semantic_class_tokens

MAX_ANCESTOR_LEVELS = 4
MAX_CLASS_TOKENS = 6
MAX_CLASS_COMBO = 3
MAX_NEAR_MISSES = 5
# Refining an over-matching candidate is only worth doing for the few that
# came closest; every page has many that will never be exact.
MAX_REFINED_CANDIDATES = 12
MAX_REFINEMENTS_PER_CANDIDATE = 8


@dataclass(frozen=True)
class SelectorFit:
    selector: str
    matched: int
    expected: int
    precision: float
    recall: float


@dataclass(frozen=True)
class Synthesis:
    """Either a usable selector (`fit`) or a declared failure carrying the
    candidates that came closest, so the caller can say *why* rather than
    shipping something that half works."""

    fit: SelectorFit | None
    near_misses: tuple[SelectorFit, ...] = ()

    @property
    def ok(self) -> bool:
        return self.fit is not None


def _uids(elements) -> set[str]:
    return {uid for el in elements if (uid := el.get(UID_ATTR)) is not None}


def _tag_of(elements) -> str:
    tags = {el.tag for el in elements if isinstance(el.tag, str)}
    return tags.pop() if len(tags) == 1 else "*"


def _attr_predicates(elements, attr: str, skip: frozenset = frozenset()) -> list[str]:
    """`[attr="v"]` when every target shares one value, `[attr^="p"]` when
    they share a prefix -- the per-instance-key case `compact.paths` masks
    to `*` (`list-item-0`, `list-item-1`, ...)."""
    values = [el.get(attr) for el in elements]
    if not all(values) or any(v in skip for v in values):
        return []
    distinct = sorted(set(values))
    if len(distinct) == 1:
        return [f'[{attr}="{distinct[0]}"]']
    prefix = _shared_prefix(distinct)
    return [f'[{attr}^="{prefix}"]'] if prefix else []


def _class_predicates(elements) -> list[str]:
    """Combinations of the semantic classes every target carries.
    `semantic_class_tokens` has already dropped generated/atomic names."""
    common = set(semantic_class_tokens(elements[0].get("class", "")))
    for el in elements[1:]:
        common &= set(semantic_class_tokens(el.get("class", "")))
    tokens = sorted(common)[:MAX_CLASS_TOKENS]
    out = []
    for k in range(min(MAX_CLASS_COMBO, len(tokens)), 0, -1):
        for combo in itertools.combinations(tokens, k):
            out.append("".join("." + c for c in combo))
    return out


def _self_segments(elements, generated: frozenset = frozenset()) -> list[str]:
    """Selector fragments matching the targets by their own identity."""
    tag = _tag_of(elements)
    segments = [
        tag + pred
        for pred in _attr_predicates(elements, "data-testid")
        + _attr_predicates(elements, "id", generated)
        + _class_predicates(elements)
    ]
    segments.append(tag)
    return segments


@dataclass(frozen=True)
class _Candidate:
    """Kept in parts rather than as one string so a `:not(...)` refinement
    can be applied to the half that actually needs it -- the state class
    that separates two row sets often sits on the anchor (folhadesp.html:
    `li.c-headline.is-hidden`), not on the matched element."""

    own: str
    anchor: str | None = None
    combinator: str = " "

    def render(self) -> str:
        return self.own if self.anchor is None else f"{self.anchor}{self.combinator}{self.own}"

    def excluding(self, cls: str, *, on_anchor: bool) -> "_Candidate":
        if on_anchor:
            return _Candidate(self.own, f"{self.anchor}:not(.{cls})", self.combinator)
        return _Candidate(f"{self.own}:not(.{cls})", self.anchor, self.combinator)


def _ancestor_chain(element) -> list:
    chain = []
    node = element.getparent()
    while node is not None and len(chain) < MAX_ANCESTOR_LEVELS:
        chain.append(node)
        node = node.getparent()
    return chain


def _positional(element) -> str | None:
    """`table:nth-of-type(2)`, the element's place among its same-tag
    siblings."""
    parent = element.getparent()
    if parent is None or not isinstance(element.tag, str):
        return None
    same = [sib for sib in parent if sib.tag == element.tag]
    if len(same) < 2:
        return None
    return f"{element.tag}:nth-of-type({same.index(element) + 1})"


def _identified_segments(element, generated: frozenset = frozenset()) -> list[str]:
    """Identity fragments for one element, excluding the bare tag -- a tag
    alone anchors nothing.

    Position counts as identity when nothing else does. A page with four
    `table.wikitable` needs `table.wikitable:nth-of-type(2)` to name the
    second one; before this the only thing separating them was a Parsoid
    id, which is exactly the anchor `generated_ids` now refuses."""
    bare = _tag_of([element])
    segments = [s for s in _self_segments([element], generated) if s != bare]
    positional = _positional(element)
    if positional:
        segments += [f"{s}{positional[len(bare):]}" for s in segments]
        segments.append(positional)
    return segments


def _candidates(targets, generated: frozenset = frozenset()) -> list[_Candidate]:
    own_segments = _self_segments(targets, generated)
    out = [_Candidate(own=segment) for segment in own_segments]

    chain = _ancestor_chain(targets[0])
    for depth, ancestor in enumerate(chain):
        for anchor in _identified_segments(ancestor, generated):
            for segment in own_segments:
                out.append(_Candidate(segment, anchor, " "))
                out.append(_Candidate(segment, anchor, " > "))
            # Spelling out the intermediate tags pins the target's depth
            # below the anchor. Needed where the target has no identity of
            # its own and a descendant combinator would match a bare tag at
            # every level (oss_gov_br_whatsapp.html, all-atomic CSS).
            if depth:
                steps = " > ".join(_tag_of([node]) for node in reversed(chain[:depth]))
                for segment in own_segments:
                    out.append(_Candidate(segment, f"{anchor} > {steps}", " > "))

    seen, unique = set(), []
    for candidate in out:
        rendered = candidate.render()
        if rendered not in seen:
            seen.add(rendered)
            unique.append(candidate)
    return unique


def _own_classes(element) -> set[str]:
    return set(discriminating_class_tokens(element.get("class", "")))


def _ancestor_classes(element) -> set[str]:
    classes: set[str] = set()
    for node in _ancestor_chain(element):
        classes |= _own_classes(node)
    return classes


def _differentiating_classes(extra, targets, classes_of) -> list[str]:
    """Classes carried by every over-matched element and by no target --
    the state class that is the only thing telling two otherwise identical
    row sets apart (folhadesp.html: `is-hidden` splits 100 headlines into
    70 and 30)."""
    if not extra:
        return []
    common = classes_of(extra[0])
    for el in extra[1:]:
        common &= classes_of(el)
    for el in targets:
        common -= classes_of(el)
    return sorted(common)


@lru_cache(maxsize=4096)
def _compile(selector: str):
    """Compiling a selector is the dominant cost of the search -- the same
    fragments recur across candidates and across families of one page."""
    try:
        return CSSSelector(selector)
    except Exception:
        return None


def _evaluate(selector: str, root, target_uids: set[str]) -> tuple[SelectorFit, list] | None:
    compiled = _compile(selector)
    if compiled is None:
        return None
    try:
        matched = compiled(root)
    except Exception:
        return None
    if not matched:
        return None
    matched_uids = _uids(matched)
    hits = len(matched_uids & target_uids)
    fit = SelectorFit(
        selector=selector,
        matched=len(matched),
        expected=len(target_uids),
        precision=hits / len(matched),
        recall=hits / len(target_uids),
    )
    extra = [el for el in matched if el.get(UID_ATTR) not in target_uids]
    return fit, extra


def synthesize(targets, root, generated_ids: frozenset = frozenset()) -> Synthesis:
    """Find the selector that reaches every element of `targets` in `root`
    while matching as little else as possible.

    `targets` must be elements of `root`, stamped by `anchor.stamp_uids`.
    """
    target_uids = _uids(targets)
    if not target_uids:
        return Synthesis(fit=None)

    complete: list[SelectorFit] = []
    misses: list[SelectorFit] = []
    overshooting: list[tuple[_Candidate, list]] = []

    # Shortest first, so the simplest exact selector is found early and the
    # rest of the search can be abandoned. Without this the candidate set
    # is scanned in full: measured at 84k evaluations and 77s on
    # acervodadostecnicosgovbr.html. A bare tag goes last regardless of
    # length: `article` reaches the twenty books exactly today and stops
    # the day a second article lands on the page, while
    # `article.product_pod` says which twenty it means.
    bare = _tag_of(targets)
    for candidate in sorted(
        _candidates(targets, generated_ids),
        key=lambda c: (c.anchor is None and c.own == bare, len(c.render())),
    ):
        evaluated = _evaluate(candidate.render(), root, target_uids)
        if evaluated is None:
            continue
        fit, extra = evaluated
        if fit.recall < 1.0:
            misses.append(fit)
            continue
        if fit.precision == 1.0:
            return Synthesis(fit=fit)
        complete.append(fit)
        if len(overshooting) < MAX_REFINED_CANDIDATES:
            overshooting.append((candidate, extra))

    for candidate, extra in overshooting:
        refinements = [
            candidate.excluding(cls, on_anchor=False)
            for cls in _differentiating_classes(extra, targets, _own_classes)
        ]
        if candidate.anchor is not None:
            refinements += [
                candidate.excluding(cls, on_anchor=True)
                for cls in _differentiating_classes(extra, targets, _ancestor_classes)
            ]
        for refined in refinements[:MAX_REFINEMENTS_PER_CANDIDATE]:
            scored = _evaluate(refined.render(), root, target_uids)
            if scored is None or scored[0].recall < 1.0:
                continue
            if scored[0].precision == 1.0:
                return Synthesis(fit=scored[0])
            complete.append(scored[0])

    if not complete:
        misses.sort(key=lambda f: (-f.recall, -f.precision, len(f.selector)))
        return Synthesis(fit=None, near_misses=tuple(misses[:MAX_NEAR_MISSES]))

    complete.sort(key=lambda f: (-f.precision, len(f.selector)))
    return Synthesis(fit=complete[0])


__all__ = ["SelectorFit", "Synthesis", "synthesize"]
