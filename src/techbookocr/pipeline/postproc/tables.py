"""Tables after the arbiter: footnotes from <tfoot> and the final row — as paragraphs after the table; <table> fragments → one."""
from __future__ import annotations

import re
from copy import copy
from xml.sax.saxutils import escape

import numpy as np
from lxml import etree
from lxml import html as lhtml

from techbookocr.pipeline.columns import column_rules, row_rules, value_spans
from techbookocr.pipeline.postproc.footmarks import LINKABLE, ref_pattern
from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.sketches import _runs

_FN_START = re.compile(r"^\s*(\*{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)")


def _parse(html: str):
    try:
        return lhtml.fragment_fromstring(html, create_parent="div")
    except Exception:  # noqa: BLE001 — empty or broken HTML
        return None


def _serialize(doc) -> str:
    parts = [escape(doc.text)] if doc.text else []
    parts += [lhtml.tostring(ch, encoding="unicode") for ch in doc]
    return "".join(parts)


def _cell_paragraphs(cell) -> list[str]:
    for br in list(cell.iter("br")):
        br.tail = "\n" + (br.tail or "")
        br.drop_tag()
    return [ln.strip() for ln in cell.text_content().split("\n") if ln.strip()]


def _width(row) -> int:
    return sum(int(c.get("colspan", "1") or 1) if str(c.get("colspan", "1")).isdigit() else 1
               for c in row if c.tag in ("td", "th"))


def _remove(el) -> None:
    parent = el.getparent()
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


_NOTE_START = re.compile(r"^\s*(?:\*{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|Примечани)")


def _row_text(tr) -> str:
    return " ".join(c.text_content().strip() for c in tr if c.tag in ("td", "th")).strip()


def _footnote_rows(table) -> list:
    """Footnote rows: <tfoot> rows and the last body row with a single full-width cell, whose text
    starts with a footnote marker (*, **, ¹) or the Russian word for "Note". Rows like "Total | 3" stay in the table."""
    rows = [tr for tf in table.iter("tfoot") for tr in tf.iter("tr") if _NOTE_START.match(_row_text(tr))]
    body = [tr for tr in table.iter("tr") if not any(tf in tr.iterancestors() for tf in table.iter("tfoot"))]
    if len(body) > 1:
        last = body[-1]
        cells = [c for c in last if c.tag in ("td", "th")]
        widest = max(_width(tr) for tr in body[:-1])
        if len(cells) == 1 and widest > 1 and _NOTE_START.match(cells[0].text_content()):
            rows.append(last)
    return rows


def _row_paragraphs(tr) -> list[str]:
    """Paragraphs of a row: the cells are joined into one paragraph; inside a cell <br> splits paragraphs only if each
    part starts with a footnote marker."""
    lines = []
    for cell in tr:
        if cell.tag in ("td", "th"):
            lines += _cell_paragraphs(cell)
    if lines and all(_FN_START.match(ln) for ln in lines):
        return lines
    return [" ".join(lines)] if lines else []


def move_table_footnotes(items: list[Item]) -> int:
    """Footnotes inside tables → Footnote elements right after the table. Returns the number of moved paragraphs."""
    out: list[Item] = []
    moved = 0
    for it in items:
        out.append(it)
        if it.category != "Table" or "<t" not in it.text:
            continue
        doc = _parse(it.text)
        if doc is None:
            continue
        paras: list[str] = []
        changed = False
        for table in list(doc.iter("table")):
            frows = _footnote_rows(table)
            if len(list(table.iter("tr"))) <= len(frows):
                continue  # the table contains nothing but footnotes
            for tr in frows:
                paras += _row_paragraphs(tr)
                parent = tr.getparent()
                _remove(tr)
                if parent.tag in ("tfoot", "tbody", "thead") and len(parent) == 0:
                    _remove(parent)
                changed = True
        if not changed:
            continue
        it.text = _serialize(doc)
        for k, text in enumerate(paras, 1):
            out.append(Item(-(it.id * 100 + k), it.page, it.ord, "Footnote", text))
        moved += len(paras)
    items[:] = out
    return moved


_NEW_TABLE = re.compile(r"^\s*(?:Таблица|Табл\.|Продолжение|Окончание)", re.I)
_SPACED = re.compile(r"(?<=\b[А-Яа-яЁё]) (?=[А-Яа-яЁё]\b)")


def _is_new_table_caption(text: str) -> bool:
    """Russian captions such as "Table 13", "*Table IX.12*", "**Table 4**", spaced-out "T a b l e 13": a caption of another table."""
    t = text.lstrip("*_# \t")
    if _NEW_TABLE.match(t):
        return True
    squeezed = re.sub(r"(?<=[А-Яа-яЁё]) (?=[А-Яа-яЁё](?: |\b))", "", t)
    return _NEW_TABLE.match(squeezed) is not None

_MAX_SUBHEAD = 80
_KEEP_TAGS = ("img",)


def _between(prev, nxt) -> tuple[str, list]:
    """Text and nodes between two adjacent tables (the tail of prev, separator elements such as <p> with their tails)."""
    texts, nodes = [(prev.tail or "").strip()], []
    el = prev.getnext()
    while el is not None and el is not nxt:
        nodes.append(el)
        texts.append(el.text_content().strip())
        texts.append((el.tail or "").strip())
        el = el.getnext()
    return " ".join(t for t in texts if t), nodes


def _merge_doc(doc) -> bool:
    tables = [t for t in doc if t.tag == "table"]
    if len(tables) < 2:
        return False
    cols = {max((_width(tr) for tr in t.iter("tr")), default=0) for t in tables}
    if len(cols) != 1 or 0 in cols:
        return False
    betweens = [_between(a, b) for a, b in zip(tables, tables[1:])]
    for text, _ in betweens:
        if text and (len(text) > _MAX_SUBHEAD or _is_new_table_caption(text)):
            return False  # another table (a caption "Table 13", "Continuation"), not a fragment of this one
    n = cols.pop()
    first = tables[0]
    host = first.find("tbody")
    if host is None:
        host = first
    trailing = tables[-1].tail
    for (text, nodes), t in zip(betweens, tables[1:]):
        keep = [nd for nd in nodes if nd.tag in _KEEP_TAGS or next(nd.iter(*_KEEP_TAGS), None) is not None]
        for node in nodes:
            node.tail = None
            doc.remove(node)
        if text or keep:
            tr = etree.SubElement(host, "tr")
            td = etree.SubElement(tr, "td", colspan=str(n))
            td.text = text
            for nd in keep:  # <img> sketch places etc. are not lost: into a full-width row
                if nd.tag in _KEEP_TAGS:
                    td.append(nd)
                else:
                    for sub in nd.iter(*_KEEP_TAGS):
                        td.append(sub)
        for tr in t.iter("tr"):
            host.append(copy(tr))
        doc.remove(t)
    first.tail = trailing
    return True


def merge_table_fragments(items: list[Item]) -> int:
    """A Table block with several <table> of the same width → one table. Returns the number of merged blocks."""
    n = 0
    for it in items:
        if it.category != "Table" or it.text.lower().count("<table") < 2:
            continue
        doc = _parse(it.text)
        if doc is None:
            continue
        if _merge_doc(doc):
            it.text = _serialize(doc)
            n += 1
    return n


_EMPTY = ("", "\xa0")


def span_single_value(items: list[Item]) -> int:
    """A table row where exactly one data cell is non-empty and at least one is empty:
    the value is printed once across several columns — merge them into <td colspan="N">.

    An empty cell carries no information, so merging loses nothing and removes a false
    attachment of the value to one column (Safronov, p. 39). Rows without data (a section caption
    inside the table) and rows with dashes are left alone: a dash is a printed sign."""
    changed = 0
    for it in items:
        if it.category != "Table":
            continue
        doc = _parse(it.text)
        if doc is None:
            continue
        hit = False
        for tr in doc.iter("tr"):
            cells = [c for c in tr if c.tag in ("td", "th")]
            if len(cells) < 3 or any(c.get("colspan") for c in cells):
                continue
            data = cells[1:]
            values = [(c.text_content() or "").strip() for c in data]
            filled = [i for i, v in enumerate(values) if v not in _EMPTY]
            if len(filled) != 1 or len(values) - 1 < 1:
                continue
            keep = data[filled[0]]
            keep.set("colspan", str(len(data)))
            for c in data:
                if c is not keep:
                    _remove(c)
            label = (cells[0].text_content() or "").strip()[:40]
            it.spans.append(f'row "{label}": {values[filled[0]]} — one value spanning {len(data)} columns')
            hit = True
            changed += 1
        if hit:
            it.text = _serialize(doc)
    return changed


_EDGE_PX = 4  # a rule closer to the crop edge is the table boundary, not a column separator


def _inner(all_rules: list[int], size: int) -> list[int]:
    return [r for r in all_rules if _EDGE_PX < r < size - _EDGE_PX]


_RULE_FILL = 0.6  # share of ink pixels in the extent box above which it is a rule, not text


def _covered(spans: list[tuple[int, int]], bounds: list[int], band_ink=None) -> list[tuple[int, int]]:
    """Non-overlapping ranges of data columns (indices 1..n-1) covered by one ink run.
    band_ink is the ink mask of the band: a run with almost solid fill is a rule fragment, skip it."""
    out = []
    for sx1, sx2 in sorted(spans):
        js = [j for j in range(1, len(bounds) - 1) if sx1 < bounds[j + 1] and sx2 > bounds[j]]
        if js and js[-1] > js[0] and (not out or js[0] > out[-1][1]):
            if band_ink is not None:
                box = band_ink[:, sx1:sx2 + 1]
                if box.mean() >= _RULE_FILL or box.any(axis=1).sum() < 6:
                    continue  # a solid rule or a dash (ink in only a few rows)
            out.append((js[0], js[-1]))
    return out


def span_by_geometry(items: list[Item], images, cfg) -> int:
    """colspan by rule geometry: an ink run in a row band that spans a column
    separator merges the cells; a dash in a cell without ink was invented by the model and is cleared.
    Any mismatch of the geometry with the markup (number of rules/bands) — the table is left alone."""
    changed = 0
    for it in items:
        if it.category != "Table" or it.bbox is None:
            continue
        try:
            page = images.get(it.page)
        except (KeyError, FileNotFoundError):
            continue
        if page is None:
            continue
        doc = _parse(it.text)
        tables = list(doc.iter("table")) if doc is not None else []
        if len(tables) != 1:
            continue
        if _geometry_table(tables[0], page.crop(it.bbox), it, cfg):
            it.text = _serialize(doc)
            changed += 1
    return changed


def _text_lines(ink, y0: int, min_row_ink: int) -> list[tuple[int, int]]:
    """Bands of text lines below y0: runs of rows where the number of ink columns is at least
    min_row_ink (rule strokes and threshold noise do not reach it), merged across gaps of up to 4 px."""
    cols = ink[y0:].sum(axis=1) >= min_row_ink
    runs, out = _runs(cols), []
    for a, b in runs:
        if out and a - out[-1][1] <= 4:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(a + y0, b + y0) for a, b in out if b - a >= 4]


def _geometry_table(tbl, crop, it: Item, cfg) -> bool:
    """Geometry for real scans: tables have no full grids, so the column boundaries
    are taken from the rules of the header band and full-height rules, and the row bands from the ink
    of text lines. Any mismatch — the table is left alone."""
    w, h = crop.size
    trs = [tr for tr in tbl.iter("tr") if any(c.tag in ("td", "th") for c in tr)]
    if len(trs) < 2:
        return False
    n_cols = max(_width(tr) for tr in trs)
    min_ink = cfg.column_rule_min_ink
    hlines = _inner(row_rules(crop, min_ink), h)
    h0 = next((r for r in hlines if r > _EDGE_PX * 3), None)
    if h0 is None:
        return False  # without a header rule the heading cannot be separated from the data
    head = _inner(column_rules(crop.crop((0, 0, w, h0)), min_ink), w)
    vrules = []
    for r in sorted(set(head) | set(_inner(column_rules(crop, min_ink), w))):
        if vrules and r - vrules[-1] <= 12:
            vrules[-1] = (vrules[-1] + r) // 2  # the same rule found in the header and over the full height
        else:
            vrules.append(r)
    bounds = [0] + vrules + [w]
    if len(bounds) - 1 != n_cols:
        return False
    ink = np.asarray(crop.convert("L"), dtype=np.uint8) < 160
    all_vrules = column_rules(crop, min_ink)
    ink[hlines, :] = False  # row bands must not include rules
    for r in all_vrules:  # and column rules: their ink is present in every row
        ink[:, max(0, r - 1):r + 2] = False
    for b in bounds[1:-1]:  # dashed separators at column boundaries also merge rows
        ink[:, max(0, b - 2):b + 3] = False
    lines = _text_lines(ink, h0, max(12, round(0.018 * w)))
    body = trs[1:]
    drift = len(lines) - len(body)  # lines with a wrapped word give extra bands
    if drift < 0:
        return False
    cands = {}  # data row index → column number of its only non-dash value
    for k, tr in enumerate(body):
        cells = [c for c in tr if c.tag in ("td", "th")]
        if len(cells) != n_cols or any(c.get("colspan") or c.get("rowspan") for c in cells):
            continue
        vals = [(c.text_content() or "").strip() for c in cells]
        keepers = [j for j in range(1, n_cols) if vals[j] and vals[j] not in _DASH]
        if len(keepers) == 1:
            cands[k] = keepers[0]
    if not cands:
        return False
    hit, used = False, set()
    for m, (y1, y2) in enumerate(lines):
        spans = value_spans(crop, all_vrules + bounds[1:-1], (0, y1, w, y2))
        band_ink = ink[y1:y2]
        ranges = _covered(spans, bounds, band_ink)
        label_ink = ink[y1:y2, :bounds[1]].any()
        if not ranges or not label_ink or y2 - y1 < 8:
            continue  # not a merged value, not a row start, or a rule fragment
        lo, hi = max(0, m - drift), min(m, len(body) - 1)
        elig = [k for k in range(lo, hi + 1)
                if k in cands and k not in used and any(a <= cands[k] <= b for a, b in ranges)]
        if len(elig) != 1:
            continue  # zero or several candidates in the window — cannot assign
        k = elig[0]
        if _geometry_row(body[k], spans, band_ink, bounds, it):
            used.add(k)
            hit = True
    return hit


def _foreign_ink(band_ink, spans, bounds, a: int, b: int) -> bool:
    """Ink wider than 7 px inside columns a..b outside runs crossing the boundaries:
    a printed dash, a value of its own, or ink of a neighboring row. Such a run
    cannot be considered part of a merged value — merging is not allowed."""
    off = bounds[a]
    cols = band_ink[:, off:bounds[b + 1]].any(axis=0)
    for sx1, sx2 in spans:
        js = [j for j in range(1, len(bounds) - 1) if sx1 < bounds[j + 1] and sx2 > bounds[j]]
        if len(js) > 1:  # the run crosses a column boundary — part of a merged value
            cols[max(0, sx1 - off - 1):sx2 + 2 - off] = False
    return any(e - s >= 8 for s, e in _runs(cols))  # a rule remnant — 1–3 px


def _geometry_row(tr, spans, band_ink, bounds: list[int], it: Item) -> bool:
    cells = [c for c in tr if c.tag in ("td", "th")]
    if len(cells) != len(bounds) - 1 or any(c.get("colspan") or c.get("rowspan") for c in cells):
        return False
    label = (cells[0].text_content() or "").strip()[:40]
    hit = False
    for a, b in _covered(spans, bounds, band_ink):
        vals = [(cells[j].text_content() or "").strip() for j in range(a, b + 1)]
        keepers = [j for j, v in zip(range(a, b + 1), vals) if v and v not in _DASH]
        if len(keepers) != 1:
            continue  # no values, or several different ones under one run — leave alone
        # in the merged columns outside the crossing runs there must be no other ink:
        # a run of its own inside a cell is a printed dash or the tail of a neighboring row,
        # while a merged value is a run crossing the boundary
        if _foreign_ink(band_ink, spans, bounds, a, b):
            continue
        keep = cells[keepers[0]]
        keep.set("colspan", str(b - a + 1))
        for j in range(a, b + 1):
            if j != keepers[0]:
                _remove(cells[j])
        it.spans.append(f'row "{label}": {vals[keepers[0] - a]} — spanning {b - a + 1} columns (geometry)')
        hit = True
    pos = 0
    for c in [c for c in tr if c.tag in ("td", "th")]:
        start, pos = pos, pos + int(c.get("colspan", "1") or 1)
        if start == 0 or pos >= len(bounds):
            continue
        if (c.text_content() or "").strip() in _DASH and not len(c) \
                and not any(sx1 < bounds[pos] and sx2 > bounds[start] for sx1, sx2 in spans):
            c.text = None  # there is no ink in the cell — the dash was not printed
            it.spans.append(f'row "{label}": dash in column {start} without ink — removed (geometry)')
            hit = True
    return hit


_DASH = ("—", "–", "-", "−")
_RANGE = ("—", "–")


def _dash_run(values: list[str], i: int, step: int) -> int:
    """Length of an unbroken run of dashes from cell i in direction step (−1 left, +1 right)."""
    n = 0
    while 0 <= i + (n + 1) * step < len(values) and values[i + (n + 1) * step] in _DASH:
        n += 1
    return n


def suspect_invented_dashes(items: list[Item]) -> list[tuple[int, str]]:
    """A row where a range value is surrounded by runs of dashes (at least two neighbors in total):
    the model might have drawn in dashes instead of a value printed across several columns
    (Safronov, p. 44). Not corrected automatically — a dash may be printed in the book;
    the row goes into quality.md."""
    out = []
    for it in items:
        if it.category != "Table":
            continue
        doc = _parse(it.text)
        if doc is None:
            continue
        for tr in doc.iter("tr"):
            cells = [c for c in tr if c.tag in ("td", "th")]
            if len(cells) < 4 or any(c.get("colspan") for c in cells):
                continue
            values = [(c.text_content() or "").strip() for c in cells[1:]]
            for i, v in enumerate(values):
                if not v or v in _DASH or not any(d in v for d in _RANGE):
                    continue
                n = _dash_run(values, i, -1) + _dash_run(values, i, 1)
                if n >= 2:
                    label = (cells[0].text_content() or "").strip()[:40]
                    out.append((it.id, f'row "{label}": {n} dashes next to value "{v}"'))
    return out


_PROMOTE = re.compile(r"^\s*(\*{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)\s+\S")


def promote_footnotes(items: list[Item], max_len: int = 400) -> int:
    """Text starting with a footnote marker (*, **, ¹) → Footnote, if it stands at the page tail or if earlier on the
    page (in text or a table cell) there is a reference to this marker. dots often returns footnotes as Text blocks."""
    by_page: dict[str, list[Item]] = {}
    for it in items:
        by_page.setdefault(it.page, []).append(it)

    def footnote_like(it: Item) -> bool:
        return it.category == "Text" and len(it.text) <= max_len and _PROMOTE.match(it.text) is not None

    n = 0
    for page_items in by_page.values():
        tail = len(page_items)
        while tail > 0 and (page_items[tail - 1].category == "Footnote" or footnote_like(page_items[tail - 1])):
            tail -= 1
        for i, it in enumerate(page_items):
            if not footnote_like(it):
                continue
            marker = _PROMOTE.match(it.text).group(1)
            referenced = any(o.category in LINKABLE and ref_pattern(marker).search(o.text)
                             for o in page_items[:i])
            if i >= tail or referenced:
                it.category = "Footnote"
                n += 1
    return n
