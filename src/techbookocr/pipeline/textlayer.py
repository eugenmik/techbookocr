"""Text extraction from the text layer of a born-digital PDF (no OCR)."""
from __future__ import annotations

import io
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import pymupdf
from PIL import Image

from techbookocr.models.types import Block, clamp_bbox
from techbookocr.pipeline.crops import save_image
from techbookocr.pipeline.state import BookState

LayerStatus = Literal["layer", "vision", "blank"]

_MIN_LAYER_SHARE = 0.7     # share of pages with a layer for the born-digital verdict
_MAX_COLUMN_SHARE = 0.3    # share of multi-column pages, above it — reject
_IMAGE_COVER = 0.5         # a raster covering more than half the page → vision
_COLUMN_SEP = 100.0        # a second column starts this far (pt) to the right of the main column's left edge
_COLUMN_MIN_LINES = 5      # a column must hold this many lines, otherwise it is an indent
_COLUMN_MIN_WIDTH = 60.0   # median line width of a column — table/formula cells are narrower


def _column_count(page: pymupdf.Page, exclude: list[pymupdf.Rect] | None = None,
                  td: dict | None = None) -> int:
    """2 if a noticeable share of lines starts to the right of the main column's left edge by _COLUMN_SEP+.

    Line starts, not words: within a column words go at a step of about a word width, while the second
    column is hundreds of points away — first-line indents (<40 pt) do not count as a column.
    Lines inside tables are not counted — cells look like columns (so we either
    pass ready rectangles or look for tables ourselves)."""
    if exclude is None:
        exclude = table_rects(page)
    if td is None:
        td = page.get_text("dict")
    lines = [(l["bbox"][0], l["bbox"][2])
             for b in td["blocks"] if b["type"] == 0
             for l in b["lines"] if l["spans"]
             and not any(pymupdf.Rect(l["bbox"]).intersects(r) for r in exclude)]
    if len(lines) < _COLUMN_MIN_LINES * 2:
        return 1
    left = sorted(x0 for x0, _ in lines)[len(lines) // 4]
    over = [x1 - x0 for x0, x1 in lines if x0 > left + _COLUMN_SEP]
    if len(over) < _COLUMN_MIN_LINES:
        return 1
    # a text column has wide lines; narrow starts are table cells and inline formulas
    return 2 if sorted(over)[len(over) // 2] >= _COLUMN_MIN_WIDTH else 1


def page_layer_status(page: pymupdf.Page) -> LayerStatus:
    """A page with a layer / a scan for the vision pass / empty."""
    if page.rotation != 0:
        return "vision"  # the layer coordinates of a rotated page do not match the print
    cover = 0.0
    area = page.rect.width * page.rect.height
    for info in page.get_image_info():
        box = pymupdf.Rect(info["bbox"])
        cover += box.width * box.height
    if area and cover / area > _IMAGE_COVER:
        return "vision"  # a scan (including one with a hidden OCR layer of unknown quality)
    if page.get_text("words"):
        return "layer"
    return "blank"


def probe_pdf(doc: pymupdf.Document, n: int) -> bool:
    """Born-digital verdict over n pages spread across the book: a layer exists,
    few multi-column pages (the front cover/index may be in 2 columns —
    they go to the vision pass, which does not spoil the verdict)."""
    if doc.page_count == 0:
        return False
    k = min(n, doc.page_count)
    sample = sorted({round(i * (doc.page_count - 1) / max(k - 1, 1)) for i in range(k)})
    layer, multi = 0, 0
    for i in sample:
        try:
            status = page_layer_status(doc[i])
            cols = _column_count(doc[i]) if status == "layer" else 1
        except Exception:                      # a broken probe page — count as no layer
            continue
        layer += status == "layer"
        multi += cols > 1
    if layer / len(sample) < _MIN_LAYER_SHARE:
        return False
    return multi / max(layer, 1) <= _MAX_COLUMN_SHARE


# --- block extraction ---

_HEAD_DELTA = 1.0     # heading: size ≥ body + 1 pt with a different (bold) font
_TITLE_DELTA = 4.0    # large heading → Title
_SMALL_DELTA = 1.5    # small font: size < body − 1.5 pt (table text, footnotes)
_SUBSUP_RATIO = 0.75  # span smaller than the line's main size ×0.75 → sub/sup
_GAP_SPACES = 3.0     # a gap inside a line > 3 spaces → suspected dropped glyph
_SPACE_RATIO = 0.27   # space width ≈ 0.27 × font size (Times)
_FOOT_MARGIN = 0.8    # small text below 80% of the height — a footnote candidate
_CAPTION_RE = re.compile(r"^\s*(Fig\.|Table\s)\s*\S")


@dataclass(frozen=True)
class FontRoles:
    """Font roles of the book: body text, headings, small (tables/footnotes)."""
    body: tuple[str, float]
    heading: frozenset[tuple[str, float]]
    small: frozenset[tuple[str, float]]


def font_roles(doc: pymupdf.Document, page_ids: list[int]) -> FontRoles:
    """Modal (font, size) by text volume = body; larger different ones are headings, smaller ones small."""
    volume: Counter[tuple[str, float]] = Counter()
    for i in page_ids:
        if i >= doc.page_count:
            continue
        for b in doc[i].get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                for s in l["spans"]:
                    key = (s["font"], round(s["size"]))
                    volume[key] += len(s["text"])
    if not volume:
        return FontRoles(("", 0.0), frozenset(), frozenset())
    body = volume.most_common(1)[0][0]
    body_font, body_size = body
    heading = frozenset(k for k in volume
                        if k[1] >= body_size + _HEAD_DELTA and k[0] != body_font)
    small = frozenset(k for k in volume if k[1] < body_size - _SMALL_DELTA)
    return FontRoles(body, heading, small)


def _in_exclude(bbox, exclude: list[pymupdf.Rect]) -> bool:
    r = pymupdf.Rect(bbox)
    return any(r.intersects(e) and (r & e).get_area() > r.get_area() * 0.5 for e in exclude)


def suspect_gap(words: list[tuple], space_w: float) -> bool:
    """The gap between adjacent words of a line is noticeably larger than a space — probably a dropped glyph."""
    return any(nxt[0] - prev[2] > _GAP_SPACES * space_w
               for prev, nxt in zip(words, words[1:]))


def _html_escape(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _line_text(line, main_size: float, main_base: float, escape: bool = False) -> str:
    """Line: spans smaller than _SUBSUP_RATIO of the main size go into <sub>/<sup> by baseline."""
    parts = []
    for s in line["spans"]:
        t = _html_escape(s["text"]) if escape else s["text"]
        if s["size"] < main_size * _SUBSUP_RATIO and t.strip():
            tag = "sub" if s["origin"][1] > main_base else "sup"
            t = f"<{tag}>{t}</{tag}>"
        parts.append(t)
    return "".join(parts)


def _category(b, roles: FontRoles, page_h: float) -> str:
    spans = [s for l in b["lines"] for s in l["spans"] if s["text"].strip()]
    if not spans:
        return "Text"
    volume: Counter[tuple[str, float]] = Counter()
    for s in spans:
        volume[(s["font"], round(s["size"]))] += len(s["text"])
    main = volume.most_common(1)[0][0]
    text = " ".join(s["text"] for s in spans).lstrip()
    if _CAPTION_RE.match(text):
        return "Caption"
    if main in roles.heading:
        if main[1] >= roles.body[1] + _TITLE_DELTA or b["bbox"][1] < page_h * 0.1:
            return "Title"
        return "Section-header"
    if main in roles.small and b["bbox"][1] > page_h * _FOOT_MARGIN:
        return "Footnote"
    return "Text"


def extract_text(page: pymupdf.Page, roles: FontRoles, dpi: int,
                 exclude: list[pymupdf.Rect],
                 td: dict | None = None, words: list | None = None) -> tuple[list[Block], int]:
    """Text blocks of a page from the layer, excluding exclude zones (tables) — in reading order.

    Returns (blocks, suspect_gaps): blocks are models.types.Block with text in which
    lines are separated by \\n and small spans are marked <sub>/<sup>; suspect_gaps is the number of lines
    with unnatural internal gaps (dropped glyphs of the layer)."""
    scale = dpi / 72
    blocks: list[Block] = []
    space_w = roles.body[1] * _SPACE_RATIO
    if words is None:
        words = page.get_text("words")
    if td is None:
        td = page.get_text("dict")
    # pymupdf splits a line at a large gap — group words by baseline across its lines
    baselines: dict[int, list[tuple]] = {}
    for w in words:
        baselines.setdefault(round((w[1] + w[3]) / 6), []).append(w)
    gaps = 0
    for ws in baselines.values():
        ws.sort(key=lambda w: w[0])
        if space_w and suspect_gap(ws, space_w):
            gaps += 1
    for b in td["blocks"]:
        if b["type"] != 0 or _in_exclude(b["bbox"], exclude):
            continue
        lines = []
        for l in b["lines"]:
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            main = Counter(round(s["size"]) for s in spans).most_common(1)[0][0]
            bases = Counter(round(s["origin"][1], 1) for s in spans if round(s["size"]) == main)
            lines.append(_line_text(l, main, bases.most_common(1)[0][0]))
        text = "\n".join(lines).strip()
        if not text:
            continue
        x1, y1, x2, y2 = (round(v * scale) for v in b["bbox"])
        blocks.append(Block(category=_category(b, roles, page.rect.height), text=text,
                            bbox=(x1, y1, x2, y2)))
    blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
    return blocks, gaps


# --- tables ---

def cell_text(page: pymupdf.Page, rect: pymupdf.Rect, td: dict | None = None) -> str:
    """Cell text from the layer for HTML: lines via \\n, small spans as <sub>/<sup>,
    other characters escaped. td is a pre-fetched get_text("dict"), so as not to parse
    the page anew for each cell."""
    lines: list[tuple[float, list]] = []
    for b in (td or page.get_text("dict"))["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            spans = [s for s in l["spans"]
                     if s["text"].strip() and pymupdf.Rect(s["bbox"]).intersects(rect)]
            if not spans:
                continue
            fake = dict(l, spans=spans)
            main = Counter(round(s["size"]) for s in spans).most_common(1)[0][0]
            bases = Counter(round(s["origin"][1], 1) for s in spans if round(s["size"]) == main)
            lines.append((l["bbox"][1], _line_text(fake, main, bases.most_common(1)[0][0],
                                                 escape=True)))
    lines.sort(key=lambda t: t[0])
    return "\n".join(t for _, t in lines).strip()


def _edges(vals: list[float], tol: float = 3.0) -> list[float]:
    """Sorted clustered grid boundaries from the coordinates of cell edges."""
    out: list[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
        else:
            out[-1] = (out[-1] + v) / 2
    return out


def _span(a: float, b: float, edges: list[float]) -> tuple[int, int]:
    """Range of boundary indices covered by [a, b]."""
    i0 = min(range(len(edges)), key=lambda i: abs(edges[i] - a))
    i1 = min(range(len(edges)), key=lambda i: abs(edges[i] - b))
    return min(i0, i1), max(i0, i1)


def _is_bold(page: pymupdf.Page, rect: pymupdf.Rect, td: dict | None = None) -> bool:
    for b in (td or page.get_text("dict"))["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                if s["text"].strip() and pymupdf.Rect(s["bbox"]).intersects(rect):
                    return bool(s["flags"] & 16) or "bold" in s["font"].lower()
    return False


def table_confidence(cells: list[list[dict]], gap_hits: int) -> float:
    """Confidence in the reconstruction: grid completeness and suspicious gaps in cells."""
    slots = sum(len(row) for row in cells)
    if not slots:
        return 0.0
    filled = sum(1 for row in cells for c in row
                 if c and (c.get("covered") or c.get("text", "").strip()))
    conf = 1.0 - 0.6 * (1 - filled / slots)
    conf -= 0.25 * min(gap_hits, 2)
    return max(0.0, round(conf, 2))


def _cells_from_rules(page: pymupdf.Page, region: pymupdf.Rect,
                      tol: float = 3.0) -> list[pymupdf.Rect]:
    """Cell grid from rule lines inside region: find_tables missed it — restore
    the boundaries from thin rectangles (pdfFactory draws a rule as rects).
    A missing inner line ⇒ a merged cell (span)."""
    vlines: list[tuple[float, float, float]] = []   # x, y0, y1
    hlines: list[tuple[float, float, float]] = []   # y, x0, x1
    for d in page.get_drawings():
        if not region.intersects(d["rect"]):
            continue
        for it in d["items"]:
            if it[0] == "l":                        # ('l', p1, p2)
                p1, p2 = it[1], it[2]
                if abs(p1.x - p2.x) < 1:
                    vlines.append((p1.x, min(p1.y, p2.y), max(p1.y, p2.y)))
                elif abs(p1.y - p2.y) < 1:
                    hlines.append((p1.y, min(p1.x, p2.x), max(p1.x, p2.x)))
            elif it[0] == "re":                     # a thin rect = a line
                r = it[1]
                if r.width <= 2 and r.height > 3:
                    vlines.append((r.x0 + r.width / 2, r.y0, r.y1))
                elif r.height <= 2 and r.width > 3:
                    hlines.append((r.y0 + r.height / 2, r.x0, r.x1))
    xs, ys = _edges([v[0] for v in vlines], tol), _edges([h[0] for h in hlines], tol)
    if len(xs) < 2 or len(ys) < 2:
        return []

    def v_at(x: float, y0: float, y1: float) -> bool:
        return any(abs(v[0] - x) <= tol and v[1] <= y0 + tol and v[2] >= y1 - tol
                   for v in vlines)

    def h_at(y: float, x0: float, x1: float) -> bool:
        return any(abs(h[0] - y) <= tol and h[1] <= x0 + tol and h[2] >= x1 - tol
                   for h in hlines)

    cells: list[pymupdf.Rect] = []
    for j in range(len(ys) - 1):
        y0, y1 = ys[j], ys[j + 1]
        # the top and bottom horizontals of a row must cover the table width
        i = 0
        while i < len(xs) - 1:
            c0 = i
            while i + 1 < len(xs) and not v_at(xs[i + 1], y0 + tol, y1 - tol):
                i += 1                              # no separator → merge along the row
            c1 = min(i + 1, len(xs) - 1)            # reached the edge — the cell extends to the right rule
            if h_at(y0, xs[c0], xs[c1]) and h_at(y1, xs[c0], xs[c1]):
                cells.append(pymupdf.Rect(xs[c0], y0, xs[c1], y1))
            i += 1
    return cells


def _blocks_from_cells(page: pymupdf.Page, rects: list[pymupdf.Rect],
                       roles: FontRoles, scale: float,
                       td: dict | None = None, words: list | None = None) -> tuple[Block, float]:
    """HTML table from a list of rectangle cells (shared code of the two detectors)."""
    xs = _edges([v for r in rects for v in (r.x0, r.x1)])
    ys = _edges([v for r in rects for v in (r.y0, r.y1)])
    grid: list[list[dict | None]] = [[None] * (len(xs) - 1) for _ in range(len(ys) - 1)]
    gap_hits = 0
    cell_size = min((k[1] for k in roles.small), default=roles.body[1] or 9)
    space_w = cell_size * _SPACE_RATIO
    if td is None:
        td = page.get_text("dict")
    if words is None:
        words = page.get_text("words")
    for r in rects:
        c0, c1 = _span(r.x0, r.x1, xs)
        r0, r1 = _span(r.y0, r.y1, ys)
        grid[r0][c0] = {"text": cell_text(page, r, td), "colspan": c1 - c0, "rowspan": r1 - r0,
                        "th": r0 == 0 or _is_bold(page, r, td)}
        for rr in range(r0, r1):
            for cc in range(c0, c1):
                if (rr, cc) != (r0, c0):
                    grid[rr][cc] = {"covered": True}
        cw = sorted((w for w in words if pymupdf.Rect(w[:4]).intersects(r)),
                    key=lambda w: w[0])
        if space_w and suspect_gap(cw, space_w):
            gap_hits += 1
    html = ["<table>"]
    for row in grid:
        html.append("<tr>")
        for c in row:
            if c is None:
                html.append("<td></td>")
            elif c.get("covered"):
                continue
            else:
                tag = "th" if c["th"] else "td"
                attrs = ""
                if c["colspan"] > 1:
                    attrs += f' colspan="{c["colspan"]}"'
                if c["rowspan"] > 1:
                    attrs += f' rowspan="{c["rowspan"]}"'
                html.append(f"<{tag}{attrs}>{c['text'].replace(chr(10), '<br>')}</{tag}>")
        html.append("</tr>")
    html.append("</table>")
    x1, y1, x2, y2 = (round(v * scale) for v in
                      (min(r.x0 for r in rects), min(r.y0 for r in rects),
                       max(r.x1 for r in rects), max(r.y1 for r in rects)))
    return Block(category="Table", text="".join(html), bbox=(x1, y1, x2, y2)), \
        table_confidence(grid, gap_hits)


def _table_grids(page: pymupdf.Page) -> list[tuple[list[pymupdf.Rect], bool]]:
    """Rectangle cells of all tables on a page: [(cells, verified)] —
    find_tables is verified, the rule fallback in uncovered clusters is not."""
    grids: list[tuple[list[pymupdf.Rect], bool]] = []
    covered: list[pymupdf.Rect] = []
    for tab in page.find_tables().tables:
        rects = [pymupdf.Rect(r) for r in tab.cells if r]
        if len(rects) < 2:
            continue
        grids.append((rects, True))
        covered.append(pymupdf.Rect(tab.bbox))
    for cl in page.cluster_drawings():
        r = pymupdf.Rect(cl)
        if r.get_area() < 32 * 32:
            continue
        if any((r & t).get_area() > r.get_area() * 0.5 for t in covered):
            continue
        cells = _cells_from_rules(page, r)
        if len(cells) >= 4:
            grids.append((cells, False))
            covered.append(r)
    return grids


def table_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Table zones (bbox) without text extraction — for exclude in the column check."""
    return [pymupdf.Rect(min(c.x0 for c in cells), min(c.y0 for c in cells),
                         max(c.x1 for c in cells), max(c.y1 for c in cells))
            for cells, _ in _table_grids(page)]


def extract_tables(page: pymupdf.Page, roles: FontRoles,
                   dpi: int, td: dict | None = None,
                   words: list | None = None) -> list[tuple[Block, float]]:
    """Tables of a page: find_tables + a rule fallback in clusters not covered by the finds."""
    out: list[tuple[Block, float]] = []
    if td is None:
        td = page.get_text("dict")
    if words is None:
        words = page.get_text("words")
    for cells, verified in _table_grids(page):
        blk, conf = _blocks_from_cells(page, cells, roles, dpi / 72, td=td, words=words)
        out.append((blk, conf if verified else conf * 0.8))
    return out


# --- figures ---

_MIN_IMG_PT = 16          # icons/bullets smaller than this are skipped
_MIN_CLUSTER_AREA = 32 * 32


def extract_image(page: pymupdf.Page, doc: pymupdf.Document, info: dict,
                  out_dir: Path, rel: str, dpi: int, quality: int | None = None) -> bool:
    """Raster by xref directly; on failure or without an xref — a clip render of the area."""
    try:
        if info.get("xref"):
            raw = doc.extract_image(info["xref"])
            save_image(Image.open(io.BytesIO(raw["image"])), out_dir / rel, quality=quality)
            return True
    except Exception:
        pass
    try:
        pix = page.get_pixmap(clip=pymupdf.Rect(info["bbox"]), dpi=dpi, alpha=False)
        save_image(Image.frombytes("RGB", (pix.width, pix.height), pix.samples),
                   out_dir / rel, quality=quality)
        return True
    except Exception:
        return False


def extract_images(page: pymupdf.Page, doc: pymupdf.Document, out_dir: Path,
                   page_name: str, dpi: int, figure_pad: int,
                   exclude: list[pymupdf.Rect], quality: int | None = None) -> tuple[list[Block], dict[int, str]]:
    """Figures of a page: embedded rasters + vector figures via clip render.

    Returns (Picture blocks, {position in the list: rel_path}); the position in the overall
    block order is set by the caller. exclude — table zones (pt)."""
    scale = dpi / 72
    size = (round(page.rect.width * scale), round(page.rect.height * scale))
    pics: list[Block] = []
    paths: dict[int, str] = {}
    img_rects: list[pymupdf.Rect] = []

    def add(rect_pt: pymupdf.Rect) -> None:
        pad_pt = figure_pad / scale
        padded = pymupdf.Rect(rect_pt.x0 - pad_pt, rect_pt.y0 - pad_pt,
                              rect_pt.x1 + pad_pt, rect_pt.y1 + pad_pt) & page.rect
        box = clamp_bbox(tuple(round(v * scale) for v in padded), size)
        if box is None:
            return
        rel = f"images/p{page_name}_fig{len(pics)}.webp"
        info = {"bbox": tuple(padded)}
        if not extract_image(page, doc, info, out_dir, rel, dpi, quality):
            return
        pics.append(Block(category="Picture", text="", bbox=box))
        paths[len(pics) - 1] = rel

    for info in page.get_image_info(xrefs=True):
        r = pymupdf.Rect(info["bbox"])
        if r.width < _MIN_IMG_PT or r.height < _MIN_IMG_PT:
            continue
        if any(r.intersects(e) and (r & e).get_area() > r.get_area() * 0.5
               for e in exclude):
            continue                           # a raster inside a table is part of it, not a figure
        img_rects.append(r)
        pad_pt = figure_pad / scale
        padded = pymupdf.Rect(r.x0 - pad_pt, r.y0 - pad_pt,
                              r.x1 + pad_pt, r.y1 + pad_pt) & page.rect
        box = clamp_bbox(tuple(round(v * scale) for v in padded), size)
        if box is None:
            continue
        rel = f"images/p{page_name}_fig{len(pics)}.webp"
        if not extract_image(page, doc, {**info, "bbox": tuple(padded)}, out_dir, rel, dpi,
                             quality):
            continue
        pics.append(Block(category="Picture", text="", bbox=box))
        paths[len(pics) - 1] = rel
    for cl in page.cluster_drawings():
        r = pymupdf.Rect(cl)
        if r.get_area() < _MIN_CLUSTER_AREA:
            continue
        if any(r.intersects(i) and (r & i).get_area() > r.get_area() * 0.5
               for i in img_rects):
            continue
        if any(r.intersects(e) and (r & e).get_area() > r.get_area() * 0.5
               for e in exclude):
            continue
        kinds = {it[0] for d in page.get_drawings() if r.intersects(d["rect"])
                 for it in d["items"]}
        if kinds <= {"l", "re"}:                # a rule/decorations — not a figure
            continue
        add(r)
    return pics, paths


# --- extract stage ---

def _noop(msg: str) -> None:
    pass


def run_extract(state: BookState, pdf_path: Path, work_dir: Path, out_dir: Path,
                p, log: Callable[[str], None] = _noop) -> int:
    """Blocks from the text layer for layer pages. Vision pages stay pending —
    the model pass completes them; empty ones → done/blank. Returns the number processed."""
    pending = state.pages(layout_status="pending")
    if not pending:
        return 0
    stats = Counter()
    doc = pymupdf.open(str(pdf_path))
    try:
        k = min(60, len(pending))
        sample = sorted({round(i * (len(pending) - 1) / max(k - 1, 1))
                         for i in range(k)}) if k else []
        roles = font_roles(doc, [pending[i].scan for i in sample])
        for page in pending:
            t0 = time.monotonic()
            try:
                status = page_layer_status(doc[page.scan])
                if status == "blank":
                    state.set_layout(page.name, [], status="done", error="blank")
                    stats["blank_pages"] += 1
                    continue
                if status == "vision":
                    stats["vision_pages"] += 1
                    continue
                pdf_page = doc[page.scan]
                pw = pdf_page.rect.width
                dpi = page.width / pw * 72 if pw and page.width else 300
                td = pdf_page.get_text("dict")
                words = pdf_page.get_text("words")
                tables = extract_tables(pdf_page, roles, dpi, td=td, words=words)
                exclude = [pymupdf.Rect(b.bbox) / (dpi / 72) for b, _ in tables]
                if _column_count(pdf_page, exclude, td=td) > 1:
                    # multi-column page: sorting by (y,x) would mix the columns —
                    # better to hand it to dots, which tells columns apart
                    stats["vision_pages"] += 1
                    continue
                blocks, gaps = extract_text(pdf_page, roles, dpi, exclude,
                                            td=td, words=words)
                pics, pic_paths = extract_images(pdf_page, doc, out_dir, page.name,
                                                 round(dpi), p.figure_pad, exclude,
                                                 quality=p.webp_quality)
                low_ids = {id(b) for b, c in tables if c < p.textlayer_table_conf}
                img_of = {id(pics[i]): rel for i, rel in pic_paths.items()}
                merged = sorted(blocks + [b for b, _ in tables] + pics,
                                key=lambda b: (b.bbox[1], b.bbox[0]))
                images = {i: img_of[id(b)] for i, b in enumerate(merged) if id(b) in img_of}
                state.set_layout(page.name, merged, status="done",
                                 seconds=time.monotonic() - t0, images=images)
                stats["layer_pages"] += 1
                stats["suspect_gaps"] += gaps
                stats["figures"] += len(pics)
                stats["tables"] += len(tables)
                for row in state.blocks(page.name):
                    if row.category == "Table" and id(merged[row.ord]) in low_ids:
                        # targeted arbiter: drafts pending → draft B on a crop, consensus → arbiter
                        stats["tables_flagged"] += 1
                        state.update_block(row.id, origin="layer", sketches_status="skipped")
                    else:
                        state.update_block(row.id, origin="layer", drafts_status="skipped",
                                           sketches_status="skipped",
                                           consensus_status="done", final=row.text_a,
                                           final_source="layer", arbiter_status="skipped")
            except Exception as e:  # noqa: BLE001 — the layer is broken on the page → vision fallback
                state.set_page_error(page.name, f"extract: {e}")
                log(f"extract {page.name}: {e}")
                stats["vision_pages"] += 1
    finally:
        doc.close()
    state.set_meta("textlayer", "1")
    try:
        prev = json.loads(state.get_meta("extract:stats") or "{}")
    except json.JSONDecodeError:
        prev = {}
    for k, v in stats.items():                 # a resume adds to the statistics, does not overwrite
        prev[k] = prev.get(k, 0) + v
    state.set_meta("extract:stats", json.dumps(prev, ensure_ascii=False))
    return stats["layer_pages"] + stats["blank_pages"]


def render_pending_pages(state: BookState, pdf_path: Path, work_dir: Path,
                         log: Callable[[str], None] = _noop) -> int:
    """PNG for pages without a file that have pending work (layout or blocks of
    sketches/drafts/arbiter): the model stages need an image — render on demand."""
    todo = {p.name for p in state.pages(layout_status="pending")}
    for stage in ("sketches", "drafts", "arbiter"):
        todo |= {b.page for b in state.pending_blocks(stage)}
    pages = [p for p in state.pages() if p.name in todo and not p.file]
    if not pages:
        return 0
    pages_dir = work_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(pdf_path))
    n = 0
    try:
        for p in pages:
            pdf_page = doc[p.scan]
            dpi = p.width / pdf_page.rect.width * 72 if pdf_page.rect.width and p.width else 300
            pix = pdf_page.get_pixmap(dpi=round(dpi), alpha=False)
            rel = f"pages/{p.name}.png"
            save_image(Image.frombytes("RGB", (pix.width, pix.height), pix.samples),
                       pages_dir / f"{p.name}.png")
            state.update_page_file(p.name, rel, p.width, p.height)  # virtual sizes —
            n += 1                                                  # in sync with pages.json
    finally:
        doc.close()
    if n:
        log(f"render: {n} pending pages from pdf")
    return n
