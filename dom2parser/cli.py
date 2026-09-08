"""Thin CLI wrapper for manual testing/demo against the example files.

This is NOT the product -- the library's public surface is
`dom2parser.compress()`. This command just runs the pipeline built so far
against a file and prints a size-reduction report, useful while developing.
"""

from __future__ import annotations

import argparse
import sys

from lxml import etree

from .html_io import load_html_file
from .sanitize import full_sanitize
from .compact.tokens import reduction_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dom2parser")
    parser.add_argument("html_file", help="Path to an HTML file to compress")
    parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="(not yet implemented past Fase A)"
    )
    args = parser.parse_args(argv)

    original_bytes = open(args.html_file, "rb").read()
    original_text = original_bytes.decode("utf-8", errors="ignore")

    root = load_html_file(args.html_file)
    clean_root = full_sanitize(root)
    clean_text = etree.tostring(clean_root, encoding="unicode", method="html")

    report = reduction_report(original_text, clean_text)
    print(f"{args.html_file}")
    print(f"  original : {report['original']['chars']:>9} chars  {report['original']['tokens']:>8} tokens")
    print(f"  sanitized: {report['compact']['chars']:>9} chars  {report['compact']['tokens']:>8} tokens")
    print(
        f"  reduction: {report['reduction_pct']['chars']:>6}% chars   "
        f"{report['reduction_pct']['tokens']:>6}% tokens"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
