"""Tree-Edit-Distance-based Similarity for HTML tables (after PubTabNet)."""
from __future__ import annotations

import re

from apted import APTED, Config
from lxml import html as lhtml
from rapidfuzz.distance import Levenshtein

from techbookocr.eval.normalize import normalize_text


class _Node:
    def __init__(self, tag: str, colspan: int = 1, rowspan: int = 1, content: str = ""):
        self.tag, self.colspan, self.rowspan, self.content = tag, colspan, rowspan, content
        self.children: list[_Node] = []


class _Cfg(Config):
    def __init__(self, structure_only: bool):
        self.structure_only = structure_only

    def rename(self, a: _Node, b: _Node) -> float:
        if (a.tag, a.colspan, a.rowspan) != (b.tag, b.colspan, b.rowspan):
            return 1.0
        if a.tag == "td" and not self.structure_only and (a.content or b.content):
            return Levenshtein.normalized_distance(a.content, b.content)
        return 0.0

    def children(self, node: _Node) -> list[_Node]:
        return node.children


def _cell_text(td) -> str:
    imgs = " [img]" * len(td.findall(".//img"))
    return normalize_text(td.text_content() + imgs)


_BR = re.compile(r"<br\b[^>]*>", re.I)


def table_cell_texts(html: str) -> list[str]:
    """Text of every cell (td/th) of all tables; rowspan/colspan attributes are not included."""
    try:
        doc = lhtml.fromstring(_BR.sub(" ", html))
    except Exception:
        return []
    return [td.text_content() for td in doc.iter("td", "th")]


def _tree(html: str) -> tuple[_Node, int] | None:
    html = _BR.sub(" ", html)
    try:
        doc = lhtml.fromstring(html)
    except Exception:
        return None
    table = doc if doc.tag == "table" else doc.find(".//table")
    if table is None:
        return None
    root, n = _Node("table"), 1
    for tr in table.iter("tr"):
        row = _Node("tr")
        n += 1
        for td in tr:
            if td.tag not in ("td", "th"):
                continue
            try:
                colspan = int(td.get("colspan", 1))
            except (ValueError, TypeError):
                colspan = 1
            try:
                rowspan = int(td.get("rowspan", 1))
            except (ValueError, TypeError):
                rowspan = 1
            row.children.append(_Node("td", colspan, rowspan, _cell_text(td)))
            n += 1
        root.children.append(row)
    return root, n


def teds(pred_html: str, gold_html: str, structure_only: bool = False) -> float:
    gold = _tree(gold_html)
    pred = _tree(pred_html)
    if gold is None:
        raise ValueError("gold table is not valid HTML table")
    if pred is None:
        return 0.0
    dist = APTED(pred[0], gold[0], _Cfg(structure_only)).compute_edit_distance()
    return max(0.0, 1.0 - dist / max(pred[1], gold[1]))
