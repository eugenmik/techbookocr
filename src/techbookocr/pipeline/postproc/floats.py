"""Reading order of "floating" blocks: figures and tables with captions in a side column or inside a paragraph frame.
dots places them by y coordinate, while the reader (and the reference) puts them after the text of the narrow column next to them."""
from __future__ import annotations

from techbookocr.pipeline.postproc.items import Item

_FLOATS = ("Picture", "Table")
_BLOCK_SKIP = ("Footnote", "Page", "Picture", "Table")
_SIDE_OVERLAP = 0.1   # fraction of width by which a block may extend in x over the figure column and still be "side"
_INSIDE = 0.3         # fraction of a block's area inside the figure frame at which the block is considered lying "in" it
_GAP = 0.025          # y tolerance as a fraction of page height: a caption by a figure, a line right under a figure


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def _union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _groups(page: list[Item], tol: float) -> list[list[Item]]:
    """A figure or table + Caption blocks adjacent to it in x and y (chained)."""
    out: list[list[Item]] = []
    used: set[int] = set()
    for f in page:
        if f.category not in _FLOATS or f.bbox is None or f.id in used:
            continue
        g = [f]
        used.add(f.id)
        grew = True
        while grew:
            grew = False
            box = _union([m.bbox for m in g])
            for c in page:
                if c.category != "Caption" or c.bbox is None or c.id in used:
                    continue
                if _overlap(c.bbox[0], c.bbox[2], box[0], box[2]) > 0 and \
                        _overlap(c.bbox[1], c.bbox[3], box[1] - tol, box[3] + tol) > 0:
                    g.append(c)
                    used.add(c.id)
                    grew = True
        out.append(sorted(g, key=lambda m: page.index(m)))
    return out


def _side_anchor(page: list[Item], blocks: list[Item], box, tol: float) -> Item | None:
    """The last block of the narrow column to the left of a figure (and lines continuing it right under the figure)."""
    gx0, gy0, gx1, gy1 = box
    side = []
    for b in blocks:
        bx0, by0, bx1, by1 = b.bbox
        ix, iy = _overlap(bx0, bx1, gx0, gx1), _overlap(by0, by1, gy0, gy1)
        if ix > 0 and iy > 0 and ix * iy >= _INSIDE * (bx1 - bx0) * (by1 - by0):
            return None  # a noticeable part of the block lies inside the figure frame: the column is not a side one
        if iy > 0 and ix <= _SIDE_OVERLAP * min(bx1 - bx0, gx1 - gx0) and bx0 < gx0:
            side.append(b)
    if not side:
        return None
    anchor = side[-1]
    # blocks after the column that start right under the figure still belong to the text next to it
    for b in blocks[blocks.index(anchor) + 1:]:
        if gy0 <= b.bbox[1] <= gy1 + tol and b.bbox[2] < gx1:  # a line under the figure, not across its whole width
            anchor = b
        else:
            break
    return anchor


def _multi_column(blocks: list[Item]) -> bool:
    """The page has two text columns: there are two blocks side by side (not overlapping in x, overlapping in y)."""
    for i, a in enumerate(blocks):
        for b in blocks[i + 1:]:
            if _overlap(a.bbox[0], a.bbox[2], b.bbox[0], b.bbox[2]) <= 0 < _overlap(a.bbox[1], a.bbox[3], b.bbox[1], b.bbox[3]):
                return True
    return False


def reorder_floats(items: list[Item], heights: dict[str, int]) -> int:
    """Moves the "figure/table + captions" groups of a page into place by the side-column rules
    and the y-inversion. items is modified in place; returns the number of moved groups."""
    by_page: dict[str, list[Item]] = {}
    for it in items:
        by_page.setdefault(it.page, []).append(it)
    moved = 0
    result: list[Item] = []
    for page_name, page in by_page.items():
        tol = _GAP * (heights.get(page_name) or 0)
        groups = _groups(page, tol) if tol else []
        if not groups:
            result += page
            continue
        member = {m.id for g in groups for m in g}
        blocks = [b for b in page if b.id not in member and b.bbox is not None and b.category not in _BLOCK_SKIP]
        if _multi_column(blocks):
            result += page  # several columns: leave the layout order alone
            continue
        after: dict[int, list[Item]] = {}
        before: dict[int, list[Item]] = {}
        placed: set[int] = set()
        for g in groups:
            box = _union([m.bbox for m in g])
            anchor = _side_anchor(page, blocks, box, tol)
            if anchor is not None:
                after.setdefault(anchor.id, []).extend(g)
                placed |= {m.id for m in g}
                continue
            gx0, gy0, gx1, gy1 = box
            col = [b for b in blocks if _overlap(b.bbox[0], b.bbox[2], gx0, gx1) > 0]
            pos = page.index(g[0])
            wrong = any((page.index(b) < pos and b.bbox[1] >= gy1) or (page.index(b) > pos and b.bbox[3] <= gy0)
                        for b in col)
            target = next((b for b in col if b.bbox[3] > gy0), None) if wrong else None
            if target is not None:
                before.setdefault(target.id, []).extend(g)
                placed |= {m.id for m in g}
        if not placed:
            result += page
            continue
        new: list[Item] = []
        for it in page:
            if it.id in placed:
                continue
            new += before.get(it.id, [])
            new.append(it)
            new += after.get(it.id, [])
        if [i.id for i in new] != [i.id for i in page]:
            moved += sum(1 for g in groups if g[0].id in placed)
            result += new
        else:
            result += page
    items[:] = result
    return moved
