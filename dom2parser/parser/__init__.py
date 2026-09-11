"""Fases I-K: turn a ranked family into a parser that runs on the original
document, deterministically and with no LLM in the loop.

The library has something a language model consuming the compact
representation does not: the actual target elements. That makes selector
choice a *measurable* search -- generate candidates, run them against the
real document, keep what demonstrably reaches every record -- rather than
a guess made from seven samples and a truncated path. So the parser is
synthesized here and shipped already verified.

What ships is data (`spec.ParserSpec`), never code: it is executed by
`executor` through lxml and never passes through `exec()`.
"""

from __future__ import annotations
