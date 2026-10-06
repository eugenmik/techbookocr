"""Book language from the text of the first pages: ru / en / de."""
from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

_CYR = re.compile(r"[А-Яа-яЁёІіЇїЄє]")  # Cyrillic + Ukrainian
_LAT = re.compile(r"[A-Za-zÄÖÜäöüß]")
_DE = re.compile(r"[äöüßÄÖÜ]|\b(?:der|die|das|und|nicht|mit|für|wird|ist|ein|eine)\b", re.I)
_EN = re.compile(r"\b(?:the|and|of|is|with|for|which|are|this)\b", re.I)
_MATH = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.S)
_TEXT_CATEGORIES = {"Text", "Title", "Section-header", "List-item", "Caption"}


def detect_lang(texts: Iterable[str]) -> str:
    """Cyrillic at least as much as Latin: ru; otherwise de/en by frequent words and umlauts. LaTeX is ignored.
    Zero or equal stopword hits → ru (default)."""
    text_list = list(texts)
    if not text_list:
        logger.warning("detect_lang: empty text sample, defaulting to 'ru'")
        return "ru"
    s = _MATH.sub(" ", " ".join(text_list))
    cyr, lat = len(_CYR.findall(s)), len(_LAT.findall(s))
    if cyr >= lat:
        return "ru"
    de_hits, en_hits = len(_DE.findall(s)), len(_EN.findall(s))
    if de_hits > en_hits:
        return "de"
    elif en_hits > de_hits:
        return "en"
    else:  # tie or zero hits
        return "ru"


def sample_texts(pages, blocks, n_pages: int) -> list[str]:
    """Drafts A of text blocks of the first n_pages pages of the book."""
    first = {p.name for p in sorted(pages, key=lambda p: p.idx)[:n_pages]}
    return [b.text_a for b in blocks if b.page in first and b.category in _TEXT_CATEGORIES]
