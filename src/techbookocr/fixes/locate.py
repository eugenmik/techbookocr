"""Location of a fix in book.md: the page section by its <!-- page: … scan: … --> anchor, context, token bounds."""
from __future__ import annotations

import re
from typing import NamedTuple

from techbookocr.fixes.journal import Fix
from techbookocr.pipeline.arbiter import _token_re

_ANCHOR = re.compile(r"<!-- page: [^>]*? scan: (\S+) -->")


def current(fix: Fix) -> str:
    """The variant that should be in the book now: "now" when applied, "was" when reverted."""
    return fix.now if fix.state == "applied" else fix.was


def _sections(md: str, scan: str) -> list[tuple[int, int]]:
    """The section of scan and the one after it (paragraphs are joined across pages)."""
    anchors = list(_ANCHOR.finditer(md))
    for i, m in enumerate(anchors):
        if m.group(1) == scan:
            if i + 1 >= len(anchors):
                return [(m.end(), len(md))]
            nxt = anchors[i + 1]
            end = anchors[i + 2].start() if i + 2 < len(anchors) else len(md)
            # the next section starts after the anchor text: a token must not match inside "<!-- page: 35 … -->"
            return [(m.end(), nxt.start()), (nxt.end(), end)]
    return []


class Located(NamedTuple):
    """Search result: status is found | absent | ambiguous; exact means found by "before + now + after";
    own means the place is in the fix's own scan section (False: in the next section, where the paragraph was joined)."""
    status: str
    span: tuple[int, int] | None = None
    exact: bool = False
    own: bool = True


def locate(md: str, fix: Fix, cur: str) -> Located:
    """Look for cur on the fix's page and in the next section. First the exact "before + cur + after" in both
    sections, then the token: the own section first, an ambiguity there stops the search."""
    if not cur:
        return Located("absent")
    secs = _sections(md, fix.scan)
    if fix.before or fix.after:
        key = re.escape(fix.before + cur + fix.after)
        hits = [(a + m.start(), n) for n, (a, b) in enumerate(secs) for m in re.finditer(key, md[a:b])]
        if len(hits) == 1:
            s = hits[0][0] + len(fix.before)
            return Located("found", (s, s + len(cur)), True, hits[0][1] == 0)
    rx = _token_re(cur)
    for n, (a, b) in enumerate(secs):
        hits = [m.span() for m in rx.finditer(md[a:b])]
        if len(hits) == 1:
            return Located("found", (a + hits[0][0], a + hits[0][1]), False, n == 0)
        if len(hits) > 1:
            return Located("ambiguous")
    return Located("absent")


def find(md: str, fix: Fix, cur: str) -> tuple[int, int] | None:
    """Bounds of cur in book.md, or None (no page, no occurrence, more than one occurrence)."""
    return locate(md, fix, cur).span


def context(md: str, start: int, end: int, n: int = 40) -> tuple[str, str]:
    """Up to n characters on the left and right, not crossing page anchors."""
    lo, hi = max(0, start - n), min(len(md), end + n)
    for m in _ANCHOR.finditer(md):
        if m.end() <= start:
            lo = max(lo, m.end())
        elif m.start() >= end:
            hi = min(hi, m.start())
            break
    return md[lo:start], md[end:hi]
