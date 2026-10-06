"""Protection against foreign text in draft B: the crop of a text block may capture neighboring blocks
(a copy of a table in pipe markup, a caption, a line of a neighboring paragraph). Such text does not belong to the block."""
from __future__ import annotations

import re
from collections import defaultdict

from rapidfuzz import fuzz

from techbookocr.pipeline.consensus import canonical_text
from techbookocr.pipeline.state import BlockRow

GUARDED_KINDS = frozenset({"text", "title", "caption", "footnote", "list"})
_TOKEN = re.compile(r"\w+", re.U)
_SEP_ROW = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
MIN_LINE = 12          # shorter is too little for fuzzy comparison
SUPPORT = 85           # a B line is "present in A"
FOREIGN = 90           # a B line is "present in another block"
TABLE_SHARE = 0.6      # share of pipe-table words found in neighbors (and not found in A)


def _is_pipe_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _tokens(s: str) -> list[str]:
    return [t for t in _TOKEN.findall(canonical_text(s))]


def _find(line: str, hay: str) -> int:
    return round(fuzz.partial_ratio(line, hay)) if line and hay else 0


def _chunks(b: str) -> list[list[str]]:
    """Paragraphs of B: lists of lines, a pipe table is a separate paragraph."""
    out: list[list[str]] = []
    cur: list[str] = []
    kind = None
    for ln in b.split("\n"):
        k = "empty" if not ln.strip() else ("pipe" if _is_pipe_row(ln) else "text")
        if k == "empty":
            if cur:
                out.append(cur)
            cur, kind = [], None
            continue
        if cur and k != kind and "pipe" in (k, kind):
            out.append(cur)
            cur = []
        cur.append(ln)
        kind = k
    if cur:
        out.append(cur)
    return out


def clean_b(b: str, a: str, others: list[str]) -> str:
    """B without lines that are absent from A but present in other blocks of the page, and without duplicate pipe tables."""
    if not b.strip() or not others:
        return b
    a_canon = canonical_text(a)
    other_canon = [c for c in (canonical_text(o) for o in others) if c]
    other_tokens = {t for c in other_canon for t in _TOKEN.findall(c)}
    a_tokens = set(_TOKEN.findall(a_canon))
    kept: list[list[str]] = []
    changed = False
    for chunk in _chunks(b):
        if _is_pipe_row(chunk[0]) and len(chunk) >= 2:
            toks = [t for ln in chunk if not _SEP_ROW.match(ln) for t in _tokens(ln)]
            if toks:
                inn = sum(t in other_tokens for t in toks) / len(toks)
                ina = sum(t in a_tokens for t in toks) / len(toks)
                if inn >= TABLE_SHARE and ina < TABLE_SHARE:
                    changed = True
                    continue
        lines = []
        for ln in chunk:
            c = canonical_text(ln)
            if len(c) >= MIN_LINE and _find(c, a_canon) < SUPPORT \
                    and any(_find(c, o) >= FOREIGN for o in other_canon):
                changed = True
                continue
            lines.append(ln)
        if lines:
            kept.append(lines)
    if not changed:
        return b
    return "\n\n".join("\n".join(c) for c in kept).strip()


def sibling_index(blocks: list[BlockRow]) -> dict[str, list[BlockRow]]:
    """Page → its top-level blocks with text (the source of "foreign" text)."""
    idx: dict[str, list[BlockRow]] = defaultdict(list)
    for b in blocks:
        if b.parent is None and b.text_a and b.text_a.strip():
            idx[b.page].append(b)
    return idx


def guarded_b(blk: BlockRow, index: dict[str, list[BlockRow]]) -> str | None:
    """Draft B of a block without foreign text; None if there is no B, it failed, or it is empty after cleaning."""
    if blk.drafts_status != "done" or blk.text_b is None:
        return None
    if blk.kind not in GUARDED_KINDS:
        return blk.text_b
    cleaned = clean_b(blk.text_b, blk.text_a, [o.text_a for o in index.get(blk.page, []) if o.id != blk.id])
    return cleaned if cleaned.strip() else None
