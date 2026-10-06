"""Running heads and page numbers: removal by category and repetition, the printed number for the page anchor."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from techbookocr.eval.normalize import normalize_text

BAND = 0.08
_CAPTION_LIKE = re.compile(r"^\s*(?:Таблица|Табл\.|Продолжение|Окончание|Рис\.|Table|Tabelle|Fig\.)", re.I)
_PAGE_NUM = re.compile(r"^\s*[-—–]?\s*(\d{1,4})\s*[-—–]?\s*$")
_EDGE_NUM = re.compile(r"^(\d{1,4})\s+\S|\S\s+(\d{1,4})$")
_BODY = {"Text", "Section-header", "Title"}


@dataclass
class HeaderInfo:
    drop: set[int] = field(default_factory=set)                 # ids of running-head blocks
    recategorize: dict[int, str] = field(default_factory=dict)  # "Table IV.16" in Page-header → Caption
    printed: dict[str, str | None] = field(default_factory=dict)


def _text(b) -> str:
    return b.final if b.final is not None else b.text_a


def _in_band(b, height: int) -> bool:
    return b.bbox is not None and (b.bbox[3] <= BAND * height or b.bbox[1] >= (1 - BAND) * height)


def _signature(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "", normalize_text(text).lower())).strip()


def _number(text: str) -> int | None:
    m = _PAGE_NUM.match(text)
    if m:
        return int(m.group(1))
    m = _EDGE_NUM.search(text.strip())
    return int(m.group(1) or m.group(2)) if m else None


def consistent_numbers(order: list[str], cands: dict[str, int], window: int = 3) -> dict[str, str | None]:
    """A candidate is accepted if a neighboring candidate (no further than window pages) agrees with it: the difference of numbers
    equals the difference of positions. Gaps between two agreeing numbers are filled.
    If a number appears on 2+ pages in different agreement chains, it is kept only on the page
    of the longest chain; the rest → None."""
    pos = {name: i for i, name in enumerate(order)}
    named = [n for n in order if n in cands]
    ok: dict[str, int] = {}
    for i, n in enumerate(named):
        for m in named[max(0, i - 1):i] + named[i + 1:i + 2]:
            if abs(pos[m] - pos[n]) <= window and cands[m] - cands[n] == pos[m] - pos[n]:
                ok[n] = cands[n]
                break

    # Build explicit chains by following consistency relationships
    # For each starting page, trace both backward and forward to form complete chains
    chains_by_num: dict[int, list[list[str]]] = defaultdict(list)
    visited: set[str] = set()

    for start_idx, start_page in enumerate(order):
        if start_page not in ok or start_page in visited:
            continue

        num = ok[start_page]
        chain = [start_page]
        visited.add(start_page)

        # Extend backward: find pages to the left that are consistent with our chain start
        for back_idx in range(start_idx - 1, -1, -1):
            back_page = order[back_idx]
            if back_page not in ok or back_page in visited:
                continue
            # Check consistency between back_page and current chain start
            if ok[back_page] == num and (abs(pos[back_page] - pos[chain[0]]) <= window and
                                         ok[back_page] - ok[chain[0]] == pos[back_page] - pos[chain[0]]):
                chain.insert(0, back_page)
                visited.add(back_page)
            else:
                break

        # Extend forward: find pages to the right that are consistent with our chain end
        for fwd_idx in range(start_idx + 1, len(order)):
            fwd_page = order[fwd_idx]
            if fwd_page not in ok or fwd_page in visited:
                continue
            # Check consistency between fwd_page and current chain end
            if ok[fwd_page] == num and (abs(pos[fwd_page] - pos[chain[-1]]) <= window and
                                        ok[fwd_page] - ok[chain[-1]] == pos[fwd_page] - pos[chain[-1]]):
                chain.append(fwd_page)
                visited.add(fwd_page)
            else:
                break

        chains_by_num[num].append(chain)

    # For numbers appearing in multiple chains, keep only the longest chain
    ok_filtered = dict(ok)
    for num, chains in chains_by_num.items():
        if len(chains) > 1:
            longest = max(chains, key=len)
            for chain in chains:
                if chain is not longest:
                    for page in chain:
                        del ok_filtered[page]

    accepted = [n for n in order if n in ok_filtered]
    out: dict[str, str | None] = {}
    for n in order:
        if n in ok_filtered:
            out[n] = str(ok_filtered[n])
            continue
        prev = next((m for m in reversed(accepted) if pos[m] < pos[n]), None)
        nxt = next((m for m in accepted if pos[m] > pos[n]), None)
        if prev and nxt and ok_filtered[nxt] - ok_filtered[prev] == pos[nxt] - pos[prev]:
            out[n] = str(ok_filtered[prev] + pos[n] - pos[prev])
        else:
            out[n] = None
    return out


def analyze_headers(pages, blocks, min_repeats: int = 3) -> HeaderInfo:
    heights = {p.name: p.height for p in pages}
    order = [p.name for p in sorted(pages, key=lambda p: p.idx)]
    info = HeaderInfo()

    # Build signature→blocks map to track both pages and vertical positions
    sig_blocks: dict[str, list[tuple[str, int, int | None]]] = defaultdict(list)  # sig → (page, block_id, center_y)
    for b in blocks:
        if b.category in _BODY and _in_band(b, heights[b.page]):
            s = _signature(_text(b))
            if s and len(s) >= 4 and len(s) <= 80:  # Require minimum 4 characters
                center_y = (b.bbox[1] + b.bbox[3]) // 2 if b.bbox else None
                sig_blocks[s].append((b.page, b.id, center_y))

    # Filter: signature must appear on >= min_repeats pages AND have similar vertical position
    repeated: set[str] = set()
    for s, blocks_list in sig_blocks.items():
        pages_set = set(page for page, _, _ in blocks_list)
        if len(pages_set) < min_repeats:
            continue
        # Check vertical position similarity (center y within 3% of page height)
        centers_y = [cy for _, _, cy in blocks_list if cy is not None]
        if centers_y:
            # Get typical page height
            typical_height = max(heights[page] for page, _, _ in blocks_list)
            avg_center = sum(centers_y) / len(centers_y)
            tolerance = 0.03 * typical_height
            if all(abs(cy - avg_center) <= tolerance for cy in centers_y):
                repeated.add(s)
        else:
            # No bbox info: accept by repetition alone
            repeated.add(s)

    # Collect page number candidates: prefer bare numbers over edge numbers
    cands: dict[str, int] = {}
    for page_name in order:
        page_cands: list[tuple[int, int]] = []  # (priority, number) where priority: 0=bare, 1=edge
        for b in blocks:
            if b.page != page_name:
                continue
            text = _text(b)
            if _CAPTION_LIKE.match(text):
                if b.category in ("Page-header", "Page-footer"):
                    info.recategorize[b.id] = "Caption"
                continue
            # Check if it's a bare page number (whole text is just a number)
            m_bare = _PAGE_NUM.match(text)
            if m_bare:
                n = int(m_bare.group(1))
                page_cands.append((0, n))  # Bare number: priority 0
            else:
                # Check for edge number
                m_edge = _EDGE_NUM.search(text.strip())
                if m_edge:
                    n = int(m_edge.group(1) or m_edge.group(2))
                    page_cands.append((1, n))  # Edge number: priority 1

        # Pick the best candidate (lowest priority = bare > edge)
        if page_cands:
            page_cands.sort()
            cands[page_name] = page_cands[0][1]

    # Now mark headers for dropping
    for b in blocks:
        text = _text(b)
        if _CAPTION_LIKE.match(text):
            if b.category in ("Page-header", "Page-footer"):
                info.recategorize[b.id] = "Caption"
            continue
        if b.category in ("Page-header", "Page-footer"):
            header = True
        elif b.category in _BODY and _in_band(b, heights[b.page]):
            header = _signature(text) in repeated or bool(_PAGE_NUM.match(text))
        else:
            header = False
        if header:
            info.drop.add(b.id)

    info.printed = consistent_numbers(order, cands)
    return info
