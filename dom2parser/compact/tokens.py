"""Size measurement helpers: chars and (approximate) LLM tokens."""

from __future__ import annotations

_ENCODING_NAME = "cl100k_base"
_encoding = None
_tried_tiktoken = False


def _get_encoding():
    global _encoding, _tried_tiktoken
    if _tried_tiktoken:
        return _encoding
    _tried_tiktoken = True
    try:
        import tiktoken

        _encoding = tiktoken.get_encoding(_ENCODING_NAME)
    except ImportError:
        _encoding = None
    return _encoding


def count_chars(text: str) -> int:
    return len(text)


def count_tokens(text: str) -> int:
    """Token count via tiktoken if installed, else a chars/4 approximation
    (a common rule of thumb for English/Portuguese mixed HTML text)."""
    encoding = _get_encoding()
    if encoding is not None:
        return len(encoding.encode(text, disallowed_special=()))
    return max(1, len(text) // 4)


def measure(text: str) -> dict:
    return {"chars": count_chars(text), "tokens": count_tokens(text)}


def reduction_report(original: str, compact: str) -> dict:
    orig = measure(original)
    comp = measure(compact)
    report = {"original": orig, "compact": comp, "reduction_pct": {}}
    for key in ("chars", "tokens"):
        if orig[key]:
            report["reduction_pct"][key] = round(100 * (1 - comp[key] / orig[key]), 1)
        else:
            report["reduction_pct"][key] = 0.0
    return report
