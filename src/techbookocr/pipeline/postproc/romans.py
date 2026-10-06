"""Roman chapter numbers in references: dots reads "I" as "1" ("Fig. 1.28" instead of "Fig. I.28")."""
from __future__ import annotations

import re

from techbookocr.pipeline.postproc.items import Item

_PREFIX = r"(?:[Рр]ис\.|[Рр]исун[а-яё]+|[Тт]абл\.|[Тт]аблиц[а-яё]+|[Гг]л\.|[Гг]лав[аеуы])\s*"
_REF = re.compile(rf"(?<![\w.])({_PREFIX})([1IVX]+)(\.\s?\d+)(?![\d]|\.\d)")
_ARABIC = re.compile(rf"(?<![\w.])(?:{_PREFIX})(\d+)\.\s?(\d+)(?![\d]|\.\d)")
_VALID = re.compile(r"^X{0,3}(?:IX|IV|V?I{0,3})$")
_CATS = frozenset({"Text", "Caption", "List-item", "Section-header", "Title", "Footnote", "Table"})
RATIO = 3  # distinct Roman references must number at least RATIO × Arabic ones with a chapter not made of ones


def roman_chapter(part: str) -> str | None:
    """A chapter-number part with "1" instead of "I" → a Roman numeral; None if it is not a Roman numeral or is already Roman."""
    if "1" not in part:
        return None
    roman = part.replace("1", "I")
    return roman if roman and _VALID.match(roman) else None


def book_is_roman(items: list[Item]) -> bool:
    """The book numbers chapters in Roman: distinct Roman references (IV.15, VI.31) ≥ RATIO × distinct Arabic
    references with a chapter not made only of ones (3.2, 4.3), and at least one Roman chapter contains V or X."""
    roman: set[str] = set()
    arabic: set[str] = set()
    for it in items:
        if it.category not in _CATS:
            continue
        for m in _REF.finditer(it.text):
            if m.group(2).isalpha():
                roman.add(m.group(2) + m.group(3))
        for m in _ARABIC.finditer(it.text):
            if set(m.group(1)) != {"1"}:
                arabic.add(f"{m.group(1)}.{m.group(2)}")
    has_vx = any(set(r.split(".")[0]) & {"V", "X"} for r in roman)
    return bool(roman) and has_vx and len(roman) >= RATIO * len(arabic)


def fix_roman_refs(items: list[Item], order: list[str] | None = None) -> int:
    """If at book level the chapters in references are Roman, "1.28", "11.32", "1V.4" → "I.28", "II.32", "IV.4"
    (only in references with the prefix fig./tabl./ch.). Otherwise changes nothing. Returns the number of replacements."""
    if not book_is_roman(items):
        return 0
    n = 0

    def sub(m: re.Match) -> str:
        nonlocal n
        fixed = roman_chapter(m.group(2))
        if fixed is None:
            return m.group(0)
        n += 1
        return m.group(1) + fixed + m.group(3)

    for it in items:
        if it.category in _CATS:
            it.text = _REF.sub(sub, it.text)
    return n
