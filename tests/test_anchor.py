"""Fase I: the bridge from the sanitized copy back to the original tree.

Two properties matter and neither is obvious from reading the code. The
stamp must not disturb any earlier stage -- it is an attribute on every
element, and `sanitize.dedup_subtree` hashes attributes -- and every clean
element that survives sanitization must still be able to name its
original, since that is the only thing letting a synthesized selector be
measured against the document a parser will actually run on.
"""

from pathlib import Path

import pytest
from lxml import etree

from dom2parser.anchor import UID_ATTR, build_index, originals_for, stamp_uids, strip_uids
from dom2parser.html_io import load_html_file, parse_html
from dom2parser.sanitize import attrs, boilerplate, dedup_subtree, strip

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.html"))


def _sanitize_steps(root):
    """`full_sanitize` minus its final dedup, so the dedup count can be
    observed on its own."""
    clean = strip.sanitize(root)
    boilerplate.strip_navigation(clean)
    boilerplate.strip_hidden_by_inline_style(clean)
    attrs.strip_noisy_attrs(clean)
    return clean


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_stamping_does_not_disable_subtree_dedup(path):
    """A unique attribute per element makes every subtree byte-unique, so
    a dedup that hashes the serialized subtree would silently stop
    collapsing anything. Measured before the fix: folhadesp.html went from
    1520 removed elements to 0."""
    plain = dedup_subtree.dedup_identical_subtrees(_sanitize_steps(load_html_file(path)))
    stamped = dedup_subtree.dedup_identical_subtrees(
        _sanitize_steps(stamp_uids(load_html_file(path)))
    )
    assert plain == stamped, (
        f"{path.name}: dedup removed {plain} elements without stamping but {stamped} "
        "with it -- the uid is leaking into the subtree hash"
    )


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_every_surviving_clean_element_maps_back_to_the_original(path):
    root = stamp_uids(load_html_file(path))
    clean = _sanitize_steps(root)
    dedup_subtree.dedup_identical_subtrees(clean)
    index = build_index(root)

    survivors = [el for el in clean.iter(etree.Element) if el.tag != "template-ref"]
    mapped = originals_for(survivors, index)
    assert len(mapped) == len(survivors), (
        f"{path.name}: only {len(mapped)}/{len(survivors)} clean elements resolve back "
        "to an original -- a selector synthesized from them cannot be verified"
    )


def test_mapped_original_is_the_same_element_not_a_lookalike():
    root = stamp_uids(parse_html("<ul><li class='a'>one</li><li class='a'>two</li></ul>"))
    clean = strip.sanitize(root)
    index = build_index(root)

    second = [el for el in clean.iter("li")][1]
    original = originals_for([second], index)[0]
    assert original.text == "two", (
        f"expected the second <li>, got {original.text!r} -- the index is matching by "
        "shape rather than by identity"
    )


def test_placeholders_left_by_dedup_have_no_original():
    """`dedup_subtree` inserts fresh `<template-ref>` nodes that never
    carried a stamp. Their absence from the index is expected, so
    `originals_for` drops them instead of raising."""
    root = stamp_uids(parse_html("<div><span>x</span></div>"))
    index = build_index(root)
    placeholder = etree.Element("template-ref")
    assert originals_for([placeholder], index) == []


def test_strip_uids_leaves_no_trace():
    root = stamp_uids(parse_html("<div><span>x</span></div>"))
    strip_uids(root)
    assert not [el for el in root.iter(etree.Element) if el.get(UID_ATTR) is not None]
