"""hunspell dictionaries (LibreOffice) via spylls: loaded into a cache without sudo, spelling statistics. No autocorrection."""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import httpx

from techbookocr.pipeline.postproc.homoglyphs import MARKUP

_BASE = "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/"
DICT_URLS = {
    "ru": (_BASE + "ru_RU/ru_RU.aff", _BASE + "ru_RU/ru_RU.dic"),
    "en": (_BASE + "en/en_US.aff", _BASE + "en/en_US.dic"),
    "de": (_BASE + "de/de_DE_frami.aff", _BASE + "de/de_DE_frami.dic"),
}
_CYR = re.compile(r"[А-Яа-яЁё]")
_LAT = re.compile(r"[A-Za-zÄÖÜäöüß]")
_WORD = re.compile(r"[A-Za-zÄÖÜäöüßА-Яа-яЁё]+")


def _http_get(url: str) -> bytes:
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.content


def ensure_dictionary(lang: str, cache_dir: Path, fetch: Callable[[str], bytes] = _http_get) -> Path:
    """Download <lang>.aff/.dic into cache_dir if they are missing; return the path without extension (for spylls).

    Checks the download (non-empty, for .dic the first line is an integer)."""
    cache_dir = Path(cache_dir).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    for url, ext in zip(DICT_URLS[lang], (".aff", ".dic")):
        target = cache_dir / f"{lang}{ext}"
        if not target.exists():
            tmp = target.with_name(target.name + ".tmp")
            content = fetch(url)

            # Validate download
            if not content:
                raise ValueError(f"Empty download for {url}")
            if ext == ".dic":
                # .dic file: first line should be an integer count
                try:
                    first_line = content.decode("utf-8", errors="ignore").split("\n")[0].strip()
                    int(first_line)
                except (ValueError, IndexError, UnicodeDecodeError) as e:
                    raise ValueError(f"Invalid .dic format for {url}: {e}")

            tmp.write_bytes(content)
            os.replace(tmp, target)
    return cache_dir / lang


def speller_langs(lang: str) -> list[str]:
    """The book's main language and English for Latin text in Russian and German books."""
    return {"ru": ["ru", "en"], "de": ["de", "en"]}.get(lang, ["en"])


class Speller:
    def __init__(self, langs: Iterable[str], cache_dir: Path, fetch: Callable[[str], bytes] = _http_get):
        from spylls.hunspell import Dictionary

        self.langs = list(langs)
        self._dicts = {lang: Dictionary.from_files(str(ensure_dictionary(lang, cache_dir, fetch)))
                       for lang in self.langs}
        self._cache: dict[str, bool | None] = {}

    def known(self, word: str) -> bool | None:
        """Whether the word is in the dictionary of its script; None if there is no dictionary for it."""
        if word in self._cache:
            return self._cache[word]
        names = ("ru",) if _CYR.search(word) else ("en", "de")
        dicts = [self._dicts[n] for n in names if n in self._dicts]
        result = any(d.lookup(word) for d in dicts) if dicts else None
        self._cache[word] = result
        return result


def load_speller(langs: Iterable[str], cache_dir: Path, log: Callable[[str], None] = lambda m: None) -> Speller | None:
    """A Speller, or None if the dictionaries are unavailable: the spelling statistics are then simply skipped."""
    try:
        return Speller(langs, cache_dir)
    except Exception as e:  # noqa: BLE001 — no network, broken dictionary
        log(f"spell check disabled: {type(e).__name__}: {e}")
        return None


@dataclass
class SpellStats:
    checked: int = 0
    unknown: int = 0
    top: list[tuple[str, int, list[str]]] = field(default_factory=list)  # (word, times, pages)

    @property
    def share(self) -> float:
        return self.unknown / self.checked if self.checked else 0.0


def spell_stats(items: Iterable[tuple[str, str]], speller, top_n: int = 30) -> SpellStats:
    """Statistics over (page, text) pairs: words of 3+ letters outside formulas and tags, without abbreviations."""
    stats = SpellStats()
    counts: Counter = Counter()
    pages: dict[str, list[str]] = defaultdict(list)
    for page, text in items:
        plain = " ".join(MARKUP.split(text)[0::2])
        for w in _WORD.findall(plain):
            if len(w) < 3 or (w.isupper() and len(w) <= 6):
                continue
            mixed = bool(_CYR.search(w)) and bool(_LAT.search(w))
            ok = False if mixed else speller.known(w)
            if ok is None:
                continue
            stats.checked += 1
            if not ok:
                stats.unknown += 1
                counts[w] += 1
                if page not in pages[w]:
                    pages[w].append(page)
    stats.top = [(w, n, pages[w]) for w, n in counts.most_common(top_n)]
    return stats
