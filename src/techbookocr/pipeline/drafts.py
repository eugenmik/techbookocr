"""The drafts stage: draft B from the crop of each block (HunyuanOCR for text and formulas, Chandra 2 for tables)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image

from techbookocr.models.types import BlockOCR
from techbookocr.pipeline.crops import PageImages, crop_block
from techbookocr.pipeline.state import BlockRow, BookState
from techbookocr.pipeline.transport import TransportFailed, TransportGuard

TEXT_MODEL_KINDS = frozenset({"text", "title", "caption", "footnote", "list", "formula", "page"})
TABLE_MODEL_KINDS = frozenset({"table"})


def _noop(msg: str) -> None:
    pass


MASK_KINDS = frozenset({"text", "title", "caption", "footnote", "list", "formula"})
MASK_MIN_SHARE = 0.5  # share of a table/figure area inside a crop above which it is painted over


def mask_boxes(blk: BlockRow, siblings: list[BlockRow]) -> tuple[tuple[int, int, int, int], ...]:
    """Table/Picture areas of the same page lying inside the text block's frame: their text is not the block's text
    (dots gives a wide frame for a paragraph that wraps around a table)."""
    if blk.bbox is None or blk.kind not in MASK_KINDS:
        return ()
    x1, y1, x2, y2 = blk.bbox
    out = []
    for o in siblings:
        if o.id == blk.id or o.parent is not None or o.bbox is None or o.category not in ("Table", "Picture"):
            continue
        ix = min(x2, o.bbox[2]) - max(x1, o.bbox[0])
        iy = min(y2, o.bbox[3]) - max(y1, o.bbox[1])
        area = (o.bbox[2] - o.bbox[0]) * (o.bbox[3] - o.bbox[1])
        if ix > 0 and iy > 0 and area > 0 and ix * iy / area >= MASK_MIN_SHARE:
            out.append(tuple(o.bbox))
    return tuple(out)


def block_image(page: Image.Image, blk: BlockRow, cfg, siblings: list[BlockRow] = ()) -> Image.Image:
    """Block image for the model: the whole page for kind=page, otherwise a crop with padding and upscaling;
    nested Table/Picture of neighboring blocks are painted over."""
    if blk.kind == "page" or blk.bbox is None:
        return page
    return crop_block(page, blk.bbox, cfg.crop_pad, cfg.min_line_px, cfg.max_upscale,
                      mask=mask_boxes(blk, list(siblings)))


def run_drafts(state: BookState, ocr: BlockOCR, work_dir: Path, cfg, guard: TransportGuard,
               kinds: frozenset[str], log: Callable[[str], None] = _noop) -> int:
    """Draft B for all blocks of kinds `kinds` with status pending. Returns the number of blocks processed."""
    pending = state.pending_blocks("drafts", kinds)
    images = PageImages(work_dir, {p.name: p.file for p in state.pages()})
    by_page: dict[str, list[BlockRow]] = {}
    for b in state.blocks():
        by_page.setdefault(b.page, []).append(b)
    done = 0
    for blk in pending:
        image = block_image(images.get(blk.page), blk, cfg, by_page.get(blk.page, ()))
        try:
            res = guard.call(ocr.ocr_block, image, blk.kind)
        except TransportFailed as e:
            state.update_block(blk.id, b_error=f"transport: {e}")  # stays pending
            log(f"drafts {blk.page}/{blk.ord}: transport failure: {e}")
            guard.failure(blk.id)
            continue
        guard.success()
        # if parsing failed, text is empty: keep the raw response (drafts_status=failed, consumers do not read it)
        state.update_block(blk.id, text_b=res.text or (res.raw if res.error else ""), b_error=res.error, b_seconds=res.seconds,
                           drafts_status="done" if res.error is None else "failed")
        if res.error:
            log(f"drafts {blk.page}/{blk.ord} ({blk.kind}): {res.error}")
        done += 1
    return done
