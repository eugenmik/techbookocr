"""Reconciling drafts A and B: canonicalization, CER, number multiset, the "accept / send to arbiter" decision."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from lxml import html as lhtml
from rapidfuzz.distance import Levenshtein

from techbookocr.eval.normalize import extract_numbers, normalize_text, strip_html
from techbookocr.pipeline.state import BookState

_DELIMS = (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$"))
_LATEX_WRAP = re.compile(r"\\(?:text|mathrm|mathit|mathbf|operatorname|textit|textbf)\s*\{([^{}]*)\}")
_LATEX_SPACE = re.compile(r"\\qquad|\\quad|\\[,;:! ]|~")
_INLINE_MATH = re.compile(r"\$\$(.+?)\$\$|\$([^$]+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)
_EMPH = re.compile(r"(\*\*|\*)(?=\S)(.+?)(?<=\S)\1")
_MD_PREFIX = re.compile(r"^\s{0,3}(?:#{1,6}\s+|[-*+•]\s+)", re.M)
_HYPHEN_JOIN = re.compile(r"(?<=[а-яёa-z])-\s*(?=[а-яёa-z])")


def canonical_formula(s: str) -> str:
    """LaTeX without delimiters, \\text{}/\\mathrm{} wrappers, \\left/\\right, with whitespace collapsed;
    braces ONLY around single character tokens (x^{2} → x^2, _{i} → _i)."""
    body = s.strip()
    # Remove delimiters
    for left, right in _DELIMS:
        if body.startswith(left) and body.endswith(right) and len(body) >= len(left) + len(right):
            body = body[len(left):len(body) - len(right)]
            break
    # Unwrap \text{}, \mathrm{}, etc.
    prev = None
    while prev != body:
        prev, body = body, _LATEX_WRAP.sub(r"\1", body)
    # Unify \left( \right) → ( ), \cdot → ·, \times → ×
    body = body.replace("\\left", "").replace("\\right", "")
    body = body.replace("\\cdot", "·").replace("\\times", "×")
    # Remove whitespace outside formulas
    body = _LATEX_SPACE.sub("", body)
    # Remove braces only around single character tokens
    body = re.sub(r'\{(.)\}', r'\1', body)
    # Normalize text
    return re.sub(r"\s+", "", normalize_text(body))


def canonical_text(s: str) -> str:
    """Block text for comparison: formulas canonicalized, tags and Markdown markup removed, normalized,
    in-word hyphenation removed."""
    s = _INLINE_MATH.sub(lambda m: " " + canonical_formula(next(g for g in m.groups() if g is not None)) + " ", s)
    s = strip_html(s)
    s = _MD_PREFIX.sub("", s)
    s = _EMPH.sub(r"\2", s)
    s = normalize_text(s)
    return _HYPHEN_JOIN.sub("", s)


def canonical_table(html: str) -> str:
    """Table rows: "rowspan x colspan : cell text" joined by |; th = td, thead/tbody ignored, <img> → [img]."""
    try:
        doc = lhtml.fragment_fromstring(html, create_parent="div")
    except Exception:  # noqa: BLE001 — empty or broken HTML
        return canonical_text(html)
    table = doc.find(".//table")
    if table is None:
        return canonical_text(html)
    rows = []
    for tr in table.iter("tr"):
        cells = []
        for td in tr:
            if td.tag not in ("td", "th"):
                continue
            text = canonical_text(td.text_content()) + " [img]" * len(td.findall(".//img"))
            cells.append(f"{td.get('rowspan', '1')}x{td.get('colspan', '1')}:{text.strip()}")
        rows.append("|".join(cells))
    return "\n".join(rows)


def canonical(kind: str, text: str) -> str:
    if kind == "table":
        return canonical_table(text)
    if kind == "formula":
        return canonical_formula(text)
    return canonical_text(text)


def cer(a: str, b: str) -> float:
    """Levenshtein distance divided by the length of the longer string (0 = identical, 1 = nothing in common)."""
    if not a and not b:
        return 0.0
    return Levenshtein.distance(a, b) / max(len(a), len(b))


def same_numbers(a: str, b: str) -> bool:
    return Counter(extract_numbers(a)) == Counter(extract_numbers(b))


@dataclass(frozen=True)
class Decision:
    decision: str             # accept | arbiter | nodraft
    cer: float | None
    final: str | None
    final_source: str | None  # "a" or None (the arbiter provides the result)


_SUBSCRIPT = re.compile(r"_\s*\{[^{}]*\}|_\s*\\?\w")


def formula_numbers_agree(a: str, b: str) -> bool:
    """Formula numbers of A and B match after normalization: canonical_formula strips \\text/\\mathrm and spaces
    (digits "5 5 2 0" are joined), subscripts, where B writes Cyrillic in Latin or Greek letters, are dropped."""
    return same_numbers(_SUBSCRIPT.sub("", canonical_formula(a)), _SUBSCRIPT.sub("", canonical_formula(b)))


def formula_usable(a: str) -> bool:
    """Formula A is usable as the result: non-empty and parsed (brackets and environments balanced)."""
    body = canonical_formula(a)
    if not body or a.count("{") != a.count("}") or a.count("\\begin") != a.count("\\end"):
        return False
    return a.count("\\left") == a.count("\\right")


def decide(kind: str | None, a: str, b: str | None, tau_text: float, mode: str = "cascade") -> Decision:
    if mode not in ("cascade", "fast"):
        raise ValueError(f"mode must be 'cascade' or 'fast', got {mode!r}")

    if kind is None:
        return Decision("nodraft", None, a, "a")
    if mode == "fast":
        if kind in ("table", "page"):
            return Decision("arbiter", None, None, None)
        return Decision("accept", None, a, "a")
    if kind == "formula" and formula_usable(a):
        # B (Hunyuan) writes Cyrillic subscripts in Latin and Greek letters, the arbiter copies them: A is more reliable
        if b is None:
            return Decision("accept", None, a, "a")
        d = cer(canonical(kind, a), canonical(kind, b))
        if not formula_numbers_agree(a, b):
            return Decision("arbiter", d, None, None)  # numbers differ: the arbiter decides from the image
        return Decision("accept", d, a, "a")
    if b is None or kind == "page":
        return Decision("arbiter", None, None, None)
    ca, cb = canonical(kind, a), canonical(kind, b)
    d = cer(ca, cb)

    # Both empty → arbiter (for non-skipped kinds)
    if not ca and not cb:
        return Decision("arbiter", 0.0, None, None)

    if ca == cb:
        # For formulas, also require matching numbers
        if kind == "formula" and not same_numbers(a, b):
            return Decision("arbiter", 0.0, None, None)
        return Decision("accept", 0.0, a, "a")

    if kind in ("table", "formula"):
        return Decision("arbiter", d, None, None)
    if d <= tau_text and same_numbers(a, b):
        return Decision("accept", d, a, "a")
    return Decision("arbiter", d, None, None)


def run_consensus(state: BookState, tau_text: float, mode: str = "cascade") -> dict[str, int]:
    """Decisions for all blocks with status pending (one transaction)."""
    from techbookocr.pipeline.guard import guarded_b, sibling_index  # guard uses canonical_text from here

    counts: Counter = Counter()
    index = sibling_index(state.blocks())
    with state.transaction():
        for blk in state.pending_blocks("consensus"):
            b = guarded_b(blk, index)
            d = decide(blk.kind, blk.text_a, b, tau_text, mode)
            state.update_block(blk.id, decision=d.decision, cer_ab=d.cer, final=d.final, final_source=d.final_source,
                               consensus_status="done",
                               arbiter_status="pending" if d.decision == "arbiter" else "skipped")
            counts[d.decision] += 1
    return dict(counts)
