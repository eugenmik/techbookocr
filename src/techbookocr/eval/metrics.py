"""Page quality metrics: text, numbers, tables, formulas, reading order."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from techbookocr.eval.normalize import extract_numbers, normalize_text, strip_html, strip_note_markers
from techbookocr.eval.teds import table_cell_texts, teds as teds_score

_TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)
_DISPLAY = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)
_INLINE = re.compile(r"(?<!\$)\$([^$\n]+?)\$(?!\$)|\\\((.+?)\\\)")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_SEP_ROW = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
# "## 5. Title" and "5. Title" (how the heading is written in the gold set) are stripped the same way: marker and number together
_MARKUP = re.compile(r"^\s{0,3}(?:#{1,6}\s+(?:\d+[.)]\s+)?|[-*+]\s+|\d+[.)]\s+)", re.M)
_EMPH = re.compile(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1")


@dataclass
class MdParts:
    text: str
    tables: list[str]
    formulas: list[str]
    paragraphs: list[str]


@dataclass
class PageScores:
    cer: float
    wer: float
    num_precision: float
    num_recall: float
    num_f1: float
    teds: float | None
    teds_struct: float | None
    formula_cer: float | None
    order: float | None


def _pipe_cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def _pipe_tables_to_html(md: str) -> str:
    """GFM pipe tables (header + |---| + rows) -> a plain <table><tr><td>."""
    lines, out, i = md.split("\n"), [], 0
    while i < len(lines):
        if "|" in lines[i] and i + 1 < len(lines) and "|" in lines[i + 1] and _SEP_ROW.match(lines[i + 1]):
            rows = [_pipe_cells(lines[i])]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_pipe_cells(lines[i]))
                i += 1
            body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
            out += ["", f"<table>{body}</table>", ""]
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def split_markdown(md: str) -> MdParts:
    md = _COMMENT.sub("", md)
    md = strip_note_markers(md)
    md = _pipe_tables_to_html(md)
    tables = _TABLE.findall(md)
    md = _TABLE.sub("\n\n", md)
    formulas = [a or b for a, b in _DISPLAY.findall(md)]
    md = _DISPLAY.sub("\n\n", md)
    formulas += [a or b for a, b in _INLINE.findall(md)]
    md = _INLINE.sub(" ", md)
    md = _IMAGE.sub("", md)
    md = strip_html(md)
    md = _MARKUP.sub("", md)
    md = _EMPH.sub(r"\2", md)
    paragraphs = [normalize_text(p) for p in re.split(r"\n\s*\n", md) if p.strip()]
    return MdParts(text=" ".join(paragraphs), tables=tables, formulas=[f.strip() for f in formulas], paragraphs=paragraphs)


def _cer(pred: str, gold: str) -> float:
    if not gold:
        return 0.0 if not pred else 1.0
    return min(1.0, Levenshtein.distance(pred, gold) / len(gold))


def _wer(pred: str, gold: str) -> float:
    g, p = gold.split(), pred.split()
    if not g:
        return 0.0 if not p else 1.0
    return min(1.0, Levenshtein.distance(p, g) / len(g))


def _number_tokens(parts: MdParts) -> list[str]:
    """Numbers from content only: text, table cells, formulas (without comments/links/attributes)."""
    items = [parts.text, *parts.formulas]
    for t in parts.tables:
        items += [strip_note_markers(cell) for cell in table_cell_texts(t)]
    return [n for it in items for n in extract_numbers(it)]


def _numbers(pred: MdParts, gold: MdParts) -> tuple[float, float, float]:
    p, g = Counter(_number_tokens(pred)), Counter(_number_tokens(gold))
    if not g and not p:
        return 1.0, 1.0, 1.0
    hit = sum((p & g).values())
    prec = hit / sum(p.values()) if p else 0.0
    rec = hit / sum(g.values()) if g else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def _order(pred_text: str, gold_pars: list[str]) -> float | None:
    work = pred_text
    positions: list[int] = []
    prev_end = 0
    for par in gold_pars:
        if len(par) < 30:
            continue
        al = fuzz.partial_ratio_alignment(par, work[prev_end:])
        if al and al.score >= 80:
            start, end = al.dest_start + prev_end, al.dest_end + prev_end
        else:
            al = fuzz.partial_ratio_alignment(par, work)
            if not al or al.score < 80:
                continue
            start, end = al.dest_start, al.dest_end
        positions.append(start)
        work = work[:start] + "\x00" * (end - start) + work[end:]
        prev_end = end
    if len(positions) < 2:
        return None
    pairs = [(i, j) for i in range(len(positions)) for j in range(i + 1, len(positions))
             if positions[i] != positions[j]]
    if not pairs:
        return None
    return sum(positions[i] < positions[j] for i, j in pairs) / len(pairs)


def _squash(latex: str) -> str:
    return re.sub(r"\s+", "", normalize_text(latex))


def score_page(pred_md: str, gold_md: str) -> PageScores:
    p, g = split_markdown(pred_md), split_markdown(gold_md)
    prec, rec, f1 = _numbers(p, g)
    t = ts = None
    if g.tables:
        pairs = [(p.tables[i] if i < len(p.tables) else "", gt) for i, gt in enumerate(g.tables)]
        t = sum(teds_score(pt, gt) for pt, gt in pairs) / len(pairs)
        ts = sum(teds_score(pt, gt, structure_only=True) for pt, gt in pairs) / len(pairs)
    f = _cer(_squash("".join(p.formulas)), _squash("".join(g.formulas))) if g.formulas else None
    return PageScores(
        cer=_cer(p.text, g.text), wer=_wer(p.text, g.text),
        num_precision=prec, num_recall=rec, num_f1=f1,
        teds=t, teds_struct=ts, formula_cer=f, order=_order(p.text, g.paragraphs),
    )
