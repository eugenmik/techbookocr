"""Joining hyphenated line breaks: Russian "me-\\ntalla" and "otritsa-telnykh" → a word, if it is in the dictionary or in the book."""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Iterable

from techbookocr.pipeline.postproc.homoglyphs import MARKUP

_L = "A-Za-zÄÖÜäöüßА-Яа-яЁё"
_l = "a-zäöüßа-яё"
_WHOLE = re.compile(rf"(?<![\w-])[{_L}]+(?![\w-])")
_SOFT = re.compile(rf"([{_L}]+)-[ \t]*\r?\n[ \t]*([{_l}]+)")
_INLINE = re.compile(rf"(?<![\w-])([{_L}]+)-([{_l}]+)(?![\w-])")


def book_vocabulary(texts: Iterable[str]) -> Counter:
    """Lowercase book words that occur whole — not as parts of hyphenated words.

    Also tracks inline hyphenated forms separately (e.g. "sine-zelyony").
    Excludes word parts broken by a soft hyphen or a hyphen."""
    c: Counter = Counter()
    for t in texts:
        plain = " ".join(MARKUP.split(t)[0::2])

        # Track inline hyphenated forms (e.g., "sine-zelyony") in vocabulary
        for m in _INLINE.finditer(plain):
            hyphenated_form = m.group(0).lower()
            c[hyphenated_form] += 1

        # Replace line-end hyphens (soft) with space to exclude parts from word count
        plain_no_soft = _SOFT.sub(" ", plain)

        # Replace inline hyphens with space to exclude both parts and concatenation
        plain_no_hyphen = _INLINE.sub(" ", plain_no_soft)

        # Count only whole words that are not parts of hyphenated sequences
        for m in _WHOLE.finditer(plain_no_hyphen):
            c[m.group(0).lower()] += 1
    return c


def make_is_word(vocab: Counter, speller=None) -> Callable[[str], bool]:
    def is_word(w: str) -> bool:
        if vocab[w.lower()] > 0:
            return True
        return bool(speller is not None and speller.known(w))
    return is_word


def join_hyphens(text: str, is_word: Callable[[str], bool], vocab: Counter | None = None, speller=None) -> str:
    """Hyphenation outside formulas and tags. At a line break — join if the word is known; within a line —
    join iff is_word(joined) AND NOT(speller.known(hyphenated)) AND vocab[hyphenated] < 2.

    vocab[hyphenated] >= 2 means a real compound to preserve; >= 1 from OCR breakage."""
    def soft(m: re.Match) -> str:
        joined = m.group(1) + m.group(2)
        return joined if is_word(joined) else m.group(0)

    def inline(m: re.Match) -> str:
        joined = m.group(1) + m.group(2)
        hyphenated = m.group(0).lower()

        # Condition 1: joined form must be known (vocab whole word or speller)
        if not is_word(joined):
            return m.group(0)

        # Condition 2: if speller knows the hyphenated form, keep it hyphenated
        if speller is not None and speller.known(hyphenated):
            return m.group(0)

        # Condition 3: if hyphenated form seen 2+ times in book, it's a real compound
        if vocab is not None and vocab[hyphenated] >= 2:
            return m.group(0)

        return joined

    parts = MARKUP.split(text)
    return "".join(p if i % 2 else _INLINE.sub(inline, _SOFT.sub(soft, p)) for i, p in enumerate(parts))
