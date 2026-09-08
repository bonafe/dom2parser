"""Fase A spike: measure how much htmlrag.clean_html reduces a real example
and whether the structure needed to build a parser survives.

Disposable script -- not part of the library's public API. Run with:
    python scripts/measure_htmlrag.py examples/bancodobrasil.html

RESULT (2026-09-07, htmlrag 0.1.1): on bancodobrasil.html, clean_html()
reduced chars by 83.7% but STRIPPED the `class`/`id` attributes needed to
build CSS/XPath selectors -- `lancamentos` and `tituloLancamento` no longer
appear anywhere in the output, only the raw text values survive. It also
pulls a very heavy dependency chain (torch, transformers, sentence-
transformers, langchain, faiss-cpu, full CUDA wheels -- 6GB+ in an
otherwise-empty venv) for what is meant to be a generic HTML cleaner.

DECISION: htmlrag is NOT used in the pipeline. It solves a different
problem (denoising HTML for text/QA-style RAG) and actively destroys the
structural attributes this project depends on, at a dependency cost far
out of proportion to the "sanitize" step it would replace. dom2parser's own
sanitize/ package (strip + boilerplate + attrs + dedup_subtree) is the
sanitization layer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dom2parser.compact.tokens import reduction_report

# Markers whose survival we check manually per file (selector-ish substrings,
# not full CSS -- htmlrag returns cleaned HTML text, not a DOM).
SURVIVAL_MARKERS = {
    "bancodobrasil.html": ["lancamentos", "tituloLancamento", "MERCADO", "52,74"],
    "conjuntodadosgovbr.html": ["search-result", "palavra-chave"],
    "dadosabertrosfiocruz.html": ["views-row", "views-field-title"],
}


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <html_file>")
        return 1

    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8", errors="ignore")

    try:
        from htmlrag import clean_html
    except ImportError:
        print("htmlrag is not installed in this environment. Run: pip install htmlrag")
        return 1

    cleaned = clean_html(original)

    report = reduction_report(original, cleaned)
    print(f"{path.name}")
    print(f"  original: {report['original']['chars']} chars / {report['original']['tokens']} tokens")
    print(f"  cleaned : {report['compact']['chars']} chars / {report['compact']['tokens']} tokens")
    print(f"  reduction: {report['reduction_pct']['chars']}% chars / {report['reduction_pct']['tokens']}% tokens")

    markers = SURVIVAL_MARKERS.get(path.name, [])
    if markers:
        print("  structure survival:")
        for marker in markers:
            print(f"    {marker!r:25s} -> {'OK' if marker in cleaned else 'MISSING'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
