"""Book assembly: book.md (page anchors, tables with sketches, figures with captions, footnotes), meta.json."""
from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree
from lxml import html as lhtml

from techbookocr.models.markdown import blocks_to_markdown
from techbookocr.models.types import Block
from techbookocr.pipeline.postproc.footmarks import LINKABLE, ref_pattern
from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.postproc.run import PostResult
from techbookocr.pipeline.state import PageRow

_FN_MARK = re.compile(r"^\s*(\*{1,3}|\d{1,2}\)|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)\s*")
_PROSE = ("Text", "List-item", "Caption", "Section-header", "Title")
_YEAR = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)")
_SEP = re.compile(r"_| - ")
# figure caption — a whole cell line: after <td>/<th>/<br> and before <br>/</td>/</th>
_CELL_CAPTION = re.compile(r"(<t[dh][^>]*>|<br\s*/?>)(\s*)((?:Рис|Fig|Abb)\.\s*\d+[^<]{0,8}?)(?=\s*(?:<br|</t[dh]>))")


def anchor(page: PageRow, printed: str | None) -> str:
    return f"<!-- page: {printed or '?'} scan: {page.name} -->"


# --- tables and sketches ---

def _parse_table(html: str):
    try:
        doc = lhtml.fragment_fromstring(html, create_parent="div")
    except Exception:  # noqa: BLE001 — empty or broken HTML
        return None
    return doc.find(".//table")


def _drop(el) -> None:
    """Remove an element, keeping the text after it."""
    parent = el.getparent()
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def _cells(table) -> list:
    return list(table.iter("td", "th"))


def _set_or_drop(img, path: str) -> None:
    """src of a sketch; an empty path (broken entry) means the <img> is removed, so there are no empty ones in the result."""
    if path:
        img.set("src", path)
    else:
        _drop(img)


def _serialize(doc) -> str:
    """Contents of a <div> wrapper (text + children + tails) without the wrapper itself."""
    parts = [escape(doc.text)] if doc.text else []
    parts += [lhtml.tostring(ch, encoding="unicode") for ch in doc]
    return "".join(parts)


def _holes(root) -> list:
    return [img for img in root.iter("img") if not img.get("src")]


def fill_sketches(table_html: str, sketches: list[str], b_html: str | None = None) -> tuple[str, list[str], str | None]:
    """Sketches into table cells in reading order → (HTML, sketches to output after the table, note or None).
    Processes all tables in the HTML, keeps the surrounding text; there are no empty <img> (without src) in the result."""
    try:
        doc = lhtml.fragment_fromstring(table_html, create_parent="div")
    except Exception:  # noqa: BLE001 — empty or broken HTML
        return table_html, list(sketches), ("table not parsed, sketches placed after it" if sketches else None)
    tables = list(doc.iter("table"))
    numbered = [im for im in doc.iter("img") if not im.get("src") and re.fullmatch(r"[0-9]{1,4}", im.get("n") or "")]
    if numbered and sketches:
        # the arbiter saw the sketches numbered: <img n="k"> is the place of sketch k (1..N)
        used: set[int] = set()
        for im in numbered:
            k = int(im.get("n"))
            if 1 <= k <= len(sketches) and k not in used and sketches[k - 1]:
                used.add(k)
                del im.attrib["n"]
                im.set("src", sketches[k - 1])
            else:
                _drop(im)
        for im in _holes(doc):
            _drop(im)
        rest = [p for k, p in enumerate(sketches, 1) if k not in used]
        note = (f"{len(sketches)} sketches, {len(used)} placed by arbiter: "
                f"the rest appended after the table" if rest else None)
        return _serialize(doc), rest, note
    holes = _holes(doc)
    n_holes = len(holes)

    if not tables:
        # not a table: empty <img> are removed, sketches go after
        if not holes:
            return table_html, list(sketches), ("table not parsed, sketches placed after it" if sketches else None)
        for img in holes:
            _drop(img)
        note = ("table not parsed, sketches placed after it" if sketches
                else f"0 sketches, {n_holes} <img> slots: empty <img> removed")
        return _serialize(doc), list(sketches), note

    if n_holes == len(sketches):
        for img, path in zip(holes, sketches):
            _set_or_drop(img, path)
        return _serialize(doc), [], None

    if len(tables) > 1:
        # several tables: in reading order, extra places are removed, extra sketches go after
        k = min(n_holes, len(sketches))
        for img, path in zip(holes[:k], sketches[:k]):
            _set_or_drop(img, path)
        for img in holes[k:]:
            _drop(img)
        note = f"{len(sketches)} sketches, {n_holes} <img> slots: " + (
            "extra sketches appended after tables" if len(sketches) > k else "extra empty <img> removed")
        return _serialize(doc), list(sketches[k:]), note

    table = tables[0]
    for img in holes:
        _drop(img)
    # arbiter result without <img>: take the sketch places from the Chandra (B) cells
    if sketches and b_html:
        btable = _parse_table(b_html)
        if btable is not None:
            bcells, cells = _cells(btable), _cells(table)
            slots = [i for i, c in enumerate(bcells) for im in c.iter("img") if not im.get("src")]
            if len(slots) == len(sketches) and len(bcells) == len(cells):
                for i, path in zip(slots, sketches):
                    if path:
                        etree.SubElement(cells[i], "img", src=path)
                return _serialize(doc), [], None
    # neither <img> places nor Chandra cells: captions like "Fig. 1a" as a separate cell line (atlases) — the sketch goes before the caption
    if sketches:
        out = _serialize(doc)
        i, j = out.find("<table"), out.rfind("</table>")
        if 0 <= i < j and len(_CELL_CAPTION.findall(out, i, j)) == len(sketches):
            it = iter(sketches)

            def _cap(m):
                p = next(it)
                return (f'{m[1]}{m[2]}<img src="{escape(p, {chr(34): "&quot;"})}"><br>{m[3]}'
                        if p else f'{m[1]}{m[2]}{m[3]}')

            body = _CELL_CAPTION.sub(_cap, out[i:j])
            return out[:i] + body + out[j:], [], None
    note = f"{len(sketches)} sketches, {n_holes} <img> slots: " + (
        "sketches placed after the table" if sketches else "empty <img> removed")
    return _serialize(doc), list(sketches), note


# --- footnotes ---

def link_footnotes(items: list[Item], counter: int) -> tuple[int, dict[int, str]]:
    """Page footnotes → [^n]: the first marker in the page text is replaced by a link.
    Returns (next number, {footnote id: definition}); a footnote without a found marker stays a paragraph."""
    defs: dict[int, str] = {}
    prose = [it for it in items if it.category in LINKABLE]
    for fn in (it for it in items if it.category == "Footnote"):
        m = _FN_MARK.match(fn.text)
        if not m:
            continue
        rx = ref_pattern(m.group(1))
        for it in prose:
            new, k = rx.subn(f"[^{counter}]", it.text, count=1)
            if k:
                it.text = new
                defs[fn.id] = f"[^{counter}]: {fn.text[m.end():].strip()}"
                counter += 1
                break
    return counter, defs


# --- book.md ---

def _alt(items: list[Item], i: int) -> str:
    for j in (i + 1, i - 1):
        if 0 <= j < len(items) and items[j].category == "Caption" and items[j].text.strip():
            return re.sub(r"[\[\]]", "", items[j].text.strip().splitlines()[0])[:200]
    return ""


def _render_item(it: Item, items: list[Item], i: int, notes: list[str]) -> str | None:
    if it.category == "Table":
        # broken sketch entry → empty path at its position: <img n> numbering does not shift
        paths = [(s.get("path") or "") if isinstance(s, dict) else "" for s in it.sketches]
        html, extra, note = fill_sketches(it.text, paths, it.text_b)
        if note:
            notes.append(f"{it.page}, block {it.ord}: {note}")
        parts = ([f"<!-- {it.note} -->"] if it.note else []) + [html] + [f"![]({p})" for p in extra if p]
        return "\n\n".join(parts)
    if it.category == "Picture":
        return f"![{_alt(items, i)}]({it.image})" if it.image else None
    if it.category == "Footnote":
        text = it.text.strip()
        if text:
            # Escape leading * to prevent Markdown interpretation
            if text.startswith("* "):
                text = "\\" + text
            return text
        return None
    return blocks_to_markdown([Block(it.category, it.text)]).rstrip("\n") or None


def render_book(post: PostResult, pages: list[PageRow]) -> tuple[str, list[str]]:
    """book.md and sketch notes for quality.md.
    Copies items before link_footnotes so as not to mutate PostResult (idempotency)."""
    from copy import copy

    by_page: dict[str, list[Item]] = defaultdict(list)
    for it in post.items:
        # Copy Item to avoid mutating PostResult
        it_copy = copy(it)
        by_page[it_copy.page].append(it_copy)

    out: list[str] = []
    where: dict[int, int] = {}  # element id → index in out (for paragraph stitching)
    notes: list[str] = []
    joined = {it.join_to for it in post.items if it.join_to is not None}  # paragraphs that the next page will continue
    joinable: set[int] = set()  # ids of paragraphs whose slot in out can be continued on the next page
    counter = 1
    for p in sorted(pages, key=lambda p: p.idx):
        items = by_page.get(p.name, [])
        counter, defs = link_footnotes(items, counter)
        mark = anchor(p, post.printed.get(p.name))
        start = 0
        if items and items[0].join_to in joinable:
        # Stitched paragraph: this page's anchor is inside it
            k = where[items[0].join_to]
            out[k] = f"{out[k]} {mark} {items[0].text.strip()}"
            where[items[0].id] = k
            joinable.add(items[0].id)
            start = 1
        else:
            out.append(mark)
        held: tuple[Item, str] | None = None  # paragraph that continues on the next page: after this page's footnotes
        for i in range(start, len(items)):
            it = items[i]
            if it.id in defs:
                continue
            part = _render_item(it, items, i, notes)
            if not part:
                continue
            if it.id in joined:
        # continues on the next page: this page's footnote definitions go before it, so that
        # the next page's anchor (inside the paragraph) does not carry them into a foreign section
                held = (it, part)
                continue
            where[it.id] = len(out)
            out.append(part)
        out.extend(defs.values())
        if held is not None:
            where[held[0].id] = len(out)
            joinable.add(held[0].id)
            out.append(held[1])
    return "\n\n".join(out) + "\n", notes


# --- meta.json ---

def title_author_year(stem: str) -> tuple[str, str | None, int | None]:
    """From the file name: "Author_Title_Year" or "Author - Title"; otherwise the whole name is the title."""
    m = _YEAR.search(stem)
    year = int(m.group(1)) if m else None
    parts = [p.strip() for p in _SEP.split(stem) if p.strip() and (m is None or p.strip() != m.group(1))]
    if len(parts) >= 2:
        return " ".join(parts[1:]), parts[0], year
    return stem, None, year


def book_meta(book_name: str, source: str, pages: list[PageRow], printed: dict, lang: str, mode: str,
              models: dict[str, str], quality: dict, extraction: dict | None = None,
              timings: dict[str, float] | None = None) -> dict:
    title, author, year = title_author_year(book_name)
    meta = {
        "title": title, "author": author, "year": year, "source": source, "lang": [lang], "mode": mode,
        "models": models, "pages": len(pages),
        "page_map": [{"scan": p.name, "printed": printed.get(p.name)} for p in sorted(pages, key=lambda p: p.idx)],
        "quality": quality,
    }
    if extraction:
        meta["extraction"] = extraction
    if timings:
        # seconds per stage: after work/ is deleted this is the only source for the book details and the panel forecast
        meta["timings"] = {k: round(float(v), 1) for k, v in timings.items()}
    return meta


def write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
