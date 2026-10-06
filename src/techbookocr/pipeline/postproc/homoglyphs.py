"""Latin look-alikes → Cyrillic in Cyrillic tokens and alphanumeric codes of Russian text.

Does not touch formulas ($…$, \\(…\\), \\[…\\]), HTML tags with attributes, Latin words without digits (Mn, MPa, HB),
chemical formulas (CO2, Fe3O4), tokens with Latin non-look-alike letters (HRC45), protected materials-science
designations (Ac1, A3, Ms, HRC45, etc.) and text dominated by Latin."""
from __future__ import annotations

import re

LAT_HOMO = "ABCEHKMOPTXaceopxy"
_TO_CYR = str.maketrans(LAT_HOMO, "АВСЕНКМОРТХасеорху")
_CYR = re.compile(r"[А-Яа-яЁё]")
_LAT = re.compile(r"[A-Za-z]")
_LETTERS = re.compile(r"[A-Za-zА-Яа-яЁё]")
_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[.\-][0-9A-Za-zА-Яа-яЁё]+)*")
MARKUP = re.compile(r"(\$\$.+?\$\$|\$[^$\n]+?\$|\\\(.+?\\\)|\\\[.+?\\\]|<[^>]*>)", re.S)
_PROTECTED = re.compile(r"^(A[0-4]|Ac[13m]|Ar[13m]|Acm|Arm|Ms|Mf|Md|HV|HB|HRC|HRB|HRA|HSD|KCU|KCV|AISI|SAE|DIN|ASTM|GOST)\d*$")
_ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr "
    "Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt "
    "Au Hg Tl Pb Bi U".split())
_CHEM_PART = re.compile(r"([A-Z][a-z]?)(\d*)")


def is_chemical(token: str) -> bool:
    """A formula of element symbols and digits without leading digits: CO2, Fe3O4, SiO2, Al2O3."""
    if not token or not token[0].isupper():
        return False
    pos = 0
    for m in _CHEM_PART.finditer(token):
        if m.start() != pos or m.group(1) not in _ELEMENTS:
            return False
        pos = m.end()
    return pos == len(token)


def cyrillic_context(text: str) -> bool:
    """Letters outside formulas and tags are mostly Cyrillic."""
    letters = _LETTERS.findall("".join(MARKUP.split(text)[0::2]))
    return bool(letters) and sum(bool(_CYR.match(c)) for c in letters) / len(letters) >= 0.5


def _fix_token(tok: str, cyr_context: bool) -> str:
    if _PROTECTED.match(tok):
        return tok
    lat = _LAT.findall(tok)
    if not lat or not all(c in LAT_HOMO for c in lat):
        return tok
    if _CYR.search(tok):  # mixed spelling: look-alikes → Cyrillic
        return tok.translate(_TO_CYR)
    if not cyr_context or not any(ch.isdigit() for ch in tok) or not any(c.isupper() for c in lat):
        return tok
    if any(is_chemical(part) for part in re.split(r"[.\-]", tok)):
        return tok
    return tok.translate(_TO_CYR)


def fix_homoglyphs_text(text: str) -> str:
    ctx = cyrillic_context(text)
    parts = MARKUP.split(text)
    return "".join(p if i % 2 else _TOKEN.sub(lambda m: _fix_token(m.group(0), ctx), p) for i, p in enumerate(parts))
