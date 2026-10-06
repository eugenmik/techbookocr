"""Stitching a paragraph across a page boundary and linking table continuations."""
from __future__ import annotations

import re
from typing import Callable

from techbookocr.pipeline.postproc.items import Item

_SENT_END = re.compile(r"[.!?…:;][)»\"\']* *$")
_HYPHEN_END = re.compile(r"([A-Za-zÄÖÜäöüßА-Яа-яЁё]+)-\s*$")
_FIRST_WORD = re.compile(r"^([a-zäöüßа-яё]+)")
_LIST_MARKER = re.compile(r"^[а-яa-z]\)")
_CONT = re.compile(r"^\s*(?:Продолжение|Окончание)\s+табл(?:\.|ицы)?\s*([IVXLC]+\s*\.\s*\d+|\d+(?:\.\d+)?)", re.I)


def stitch_pages(items: list[Item], order: list[str], is_word: Callable[[str], bool]) -> int:
    """The first Text of a page starting with a lowercase letter continues the last Text of the previous page (if that one is not ended
    by a period etc.). A hyphenation at the joint is joined if the word is known. Returns the number of stitches."""
    pos = {name: i for i, name in enumerate(order)}
    by_page: dict[str, list[Item]] = {}
    for it in items:
        by_page.setdefault(it.page, []).append(it)
    pages = sorted(by_page, key=pos.__getitem__)
    n = 0
    items_to_remove = []
    for prev_page, page in zip(pages, pages[1:]):
        if pos[page] - pos[prev_page] != 1:
            continue
        prev = next((it for it in reversed(by_page[prev_page]) if it.category != "Footnote"), None)
        first = by_page[page][0]
        if prev is None or prev.category != "Text" or first.category != "Text":
            continue
        nxt = first.text.lstrip()
        if not nxt or not nxt[0].isalpha() or not nxt[0].islower() or _SENT_END.search(prev.text):
            continue
        # Don't stitch if next page starts with list marker (lowercase letter + paren)
        if _LIST_MARKER.match(nxt):
            continue
        h, w = _HYPHEN_END.search(prev.text), _FIRST_WORD.match(nxt)
        if h and w and is_word(h.group(1) + w.group(1)):
            prev.text = prev.text[:h.start()].rstrip()
            nxt = h.group(1) + nxt
            # If previous item becomes empty after removing hyphen, mark it for removal
            if not prev.text:
                items_to_remove.append(prev)
        first.text = nxt
        first.join_to = prev.id
        n += 1

    # Remove empty previous items
    for item in items_to_remove:
        items.remove(item)

    return n


def mark_continuations(items: list[Item]) -> int:
    """A Russian "Continuation of table IV.15" before a table on the same page → a comment on the table; the tables are not merged."""
    n = 0
    for i, it in enumerate(items):
        m = _CONT.match(it.text) if it.category in ("Caption", "Text", "Section-header") else None
        if not m:
            continue
        ref = re.sub(r"\s+", "", m.group(1))
        for nxt in items[i + 1:i + 4]:
            if nxt.page != it.page:
                break
            if nxt.category == "Table":
                nxt.note = f"continues: table {ref}"
                n += 1
                break
    return n
