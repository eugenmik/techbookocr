"""Text normalization for comparing drafts and for metrics."""
from __future__ import annotations

import html
import re
import unicodedata

_LAT2CYR = str.maketrans("ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху")
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё]+")
_CYR = re.compile(r"[А-Яа-яЁё]")
_DASHES = str.maketrans("–—−‒‑", "-----")


def fix_homoglyphs(text: str) -> str:
    def repl(m: re.Match) -> str:
        w = m.group(0)
        return w.translate(_LAT2CYR) if _CYR.search(w) else w

    return _WORD.sub(repl, text)


_NUMRE = r"\d+(?:[.,]\d+)?"
_TIMES = re.compile(rf"(?<![\w.,])({_NUMRE})(\s*)[×хХ](\s*)(?={_NUMRE}(?!\w))")


def _times(text: str) -> str:
    """x/h -> x only between "bare" numbers (steel grades such as 12Kh18N10T are left alone)."""
    return _TIMES.sub(lambda m: f"{m.group(1)}{m.group(2)}x{m.group(3)}", text)


_QUOTES = str.maketrans({
    "\u00ab": '"', "\u00bb": '"', "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2018": "'", "\u2019": "'",
})
# Superscripts/subscripts -> base characters (exponent sign "⁻³" -> "-3").
_SCRIPTS = str.maketrans(
    "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a\u207b"
    "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089\u208a\u208b",
    "0123456789+-" "0123456789+-",
)
_KNOWN_TAG = re.compile(
    r"</?(?:br|p|div|span|sup|sub|b|i|u|em|strong|small|big|code|a|img|hr|ul|ol|li|h[1-6])\b[^>]*>",
    re.I,
)
_BR = re.compile(r"<br\b[^>]*>", re.I)


def strip_html(text: str) -> str:
    """Removes only known markup tags; "t < 500" stays. <br> -> space."""
    return _KNOWN_TAG.sub("", _BR.sub(" ", text))


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = html.unescape(text)
    text = text.translate(_SCRIPTS)
    text = fix_homoglyphs(text)
    text = text.translate(_DASHES)
    text = text.translate(_QUOTES)
    text = text.replace("{,}", ",")
    text = _times(text)
    return re.sub(r"\s+", " ", text).strip()


_THOUSANDS = re.compile(r"(?<!\d)\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+(?!\d)")
_SIGNED_NUM = re.compile(rf"(?:(?<![^\s(])-)?{_NUMRE}")
_LATEX_SCRIPT = (
    (re.compile(r"\^\{([^{}]*)\}"), r"\1"),
    (re.compile(r"_\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\^([+-]?\d)"), r"\1"),
    (re.compile(r"_(\d)"), r"\1"),
)


_FOOTNOTE_REF = re.compile(r"\[\^[^\]\s]+\]")
_FOOTNOTE_DEF = re.compile(r"^\[\^[^\]\s]+\]:\s*", re.M)
_SUPERSCRIPT_DIGITS = "¹²³⁴⁵⁶⁷⁸⁹"
# Markdown emphasis: **text**, __text__, *text*, _text_
_EMPH = re.compile(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1")
# Precompiled regex for superscript digits after long words (3+ letters)
_SUPERSCRIPT_AFTER_LONGWORD = re.compile(rf"([А-Яа-яЁёA-Za-z]{{3,}})[{re.escape(_SUPERSCRIPT_DIGITS)}]")


def strip_note_markers(text: str) -> str:
    """Remove footnote references, definitions, asterisk markers, and superscript footnote digits.

    Handles:
    - Markdown emphasis: removes paired **text**, *text*, __text__, _text_ markers (to prevent
      asterisks from being misidentified as footnote markers)
    - Markdown footnote references: [^1] -> removed
    - Markdown footnote definitions: [^1]: text -> text (definition line becomes plain paragraph)
    - Asterisk markers: word* or word** -> word (only asterisks directly attached)
    - Superscript digits: word¹ -> word (only after 3+ letter words, not unit abbreviations like m³)
    """
    # Remove markdown emphasis markers FIRST to avoid them being confused with footnote markers
    text = _EMPH.sub(r"\2", text)

    # (a) Remove footnote references
    text = _FOOTNOTE_REF.sub("", text)

    # (b) Turn footnote definitions into plain paragraphs (drop label, keep text)
    text = _FOOTNOTE_DEF.sub("", text)

    # (c) Remove bare asterisk markers
    # Remove asterisks directly attached to word/number end: word* -> word, 1,0** -> 1,0
    text = re.sub(r"([a-zA-Zа-яА-ЯЁё0-9])\*{1,3}(?=\s|$)", r"\1", text)

    # Remove leading asterisks (escape or literal) at line start, but be careful about lists.
    # Rule: strip leading `*`/`**`/`\*` note marker on a line only when NEITHER the previous
    # non-empty line NOR the next non-empty line starts with "* " or "- " (list markers).
    lines = text.split('\n')
    result_lines = []

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        # Check if this is a bullet list item or an escaped asterisk note marker
        is_bullet = stripped.startswith("* ") or stripped.startswith("- ") or stripped.startswith("** ")
        is_escaped_note = stripped.startswith(r"\* ") or stripped.startswith(r"\** ")
        is_note_marker = is_bullet or is_escaped_note

        # Check if this line is part of a list block
        is_list_block = False
        if is_note_marker:
            # Find previous non-empty line
            prev_is_bullet = False
            for j in range(i - 1, -1, -1):
                prev_stripped = lines[j].lstrip()
                if prev_stripped:  # Found a non-empty line
                    prev_is_bullet = (prev_stripped.startswith("* ") or prev_stripped.startswith("- ") or
                                     prev_stripped.startswith("** "))
                    break

            # Find next non-empty line
            next_is_bullet = False
            for j in range(i + 1, len(lines)):
                next_stripped = lines[j].lstrip()
                if next_stripped:  # Found a non-empty line
                    next_is_bullet = (next_stripped.startswith("* ") or next_stripped.startswith("- ") or
                                     next_stripped.startswith("** "))
                    break

            # It's a list block if either previous or next non-empty line is also a bullet
            is_list_block = prev_is_bullet or next_is_bullet

        # Only strip leading asterisks if NOT part of a list block
        if is_note_marker and not is_list_block:
            # Strip leading asterisks (escaped or literal)
            line = re.sub(r"^(\s*)(\\\*){1,3}\s+", r"\1", line)
            line = re.sub(r"^(\s*)\*{1,3}\s+", r"\1", line)

        result_lines.append(line)

    text = '\n'.join(result_lines)

    # (d) Remove superscript footnote digits after long words (but NOT short unit abbreviations).
    # Only remove superscript if preceded by 3+ consecutive letters (e.g., "word¹" -> "word").
    # This heuristic preserves common SI unit abbreviations: m³ (cubic meter), cm² (square cm),
    # g (gram), mm (millimeter), kg (kilogram), l (liter), etc. which are typically 1-2 letters.
    text = _SUPERSCRIPT_AFTER_LONGWORD.sub(r"\1", text)

    return text


def extract_numbers(text: str) -> list[str]:
    """Numbers from text. Exponent: ``10^{-3}`` and ``10⁻³`` -> "10-3" (both sides alike;
    the minus inside a fused "10-3" is not a number sign, so the tokens are "10", "3").
    Digit groups "1 350 000" are joined; a leading minus counts after start/space/"("."""
    for rx, rep in _LATEX_SCRIPT:
        text = rx.sub(rep, text)
    text = normalize_text(text)
    text = _THOUSANDS.sub(lambda m: re.sub(r"\D", "", m.group(0)), text)
    return _SIGNED_NUM.findall(text)
