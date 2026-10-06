"""Footnote markers: finding a footnote reference in text."""
from __future__ import annotations

import re

LINKABLE = ("Text", "List-item", "Caption", "Section-header", "Title", "Table")  # where footnote references are searched for
_UNITS = frozenset(u.lower() for u in (
    "мм см м дм км мкм кг г т мин с ч Н кН Па кПа МПа ГПа % ° °С Дж кДж Вт кВт об л мл К кал ккал".split()))
_TOKEN_END = re.compile(r"([A-Za-zА-Яа-яЁё%°]+)\s*$")


class FootRef:
    """A footnote reference: a regular expression + a ban on "unit of measurement before the marker" (m³, mm², %¹)."""

    def __init__(self, rx: re.Pattern, units: bool = False):
        self.rx, self.units = rx, units

    def _ok(self, text: str, m: re.Match) -> bool:
        if not self.units:
            return True
        tok = _TOKEN_END.search(text[:m.start()])
        return tok is None or tok.group(1).lower() not in _UNITS

    def search(self, text: str):
        return next((m for m in self.rx.finditer(text) if self._ok(text, m)), None)

    def subn(self, repl: str, text: str, count: int = 1) -> tuple[str, int]:
        m = self.search(text)
        return (text[:m.start()] + repl + text[m.end():], 1) if m else (text, 0)


def ref_pattern(marker: str) -> FootRef:
    """A footnote reference in text: a marker right after a word or (for * and superscripts) after one space;
    a superscript ²/³ after a unit of measurement (e.g. "Volume, m³") or after a digit is not a reference."""
    m = re.escape(marker)
    if marker.startswith("*"):
        return FootRef(re.compile(rf"(?<=[^\s*])(?:{m}(?!\*)|\s{m}(?=[.,;:)\]<]|\s*$))"))
    if marker[0] in "¹²³⁴⁵⁶⁷⁸⁹⁰":
        return FootRef(re.compile(rf"(?<=[^\s\d])\s?{m}"), units=marker[0] in "²³")
    return FootRef(re.compile(rf"(?<=[^\s\d]){m}"))
