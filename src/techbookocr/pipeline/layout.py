"""The layout stage: layout and draft A by the layout model over all pages of the book, figure crops."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from techbookocr.models.types import Block, PageOCR, PageResult, clamp_bbox
from techbookocr.pipeline.crops import PageImages, deskew_photo, pad_box, save_image
from techbookocr.pipeline.state import PAGE_CATEGORY, BookState
from techbookocr.pipeline.transport import TransportFailed, TransportGuard


def _noop(msg: str) -> None:
    pass


def layout_blocks(res: PageResult, size: tuple[int, int], is_blank: bool = False) -> tuple[str, list[Block]]:
    """(page status, blocks). Blocks without a frame are discarded. If there are no usable blocks and the model returned
    an error or blocks without frames, the page is failed: one "whole page" block goes to draft B and the arbiter.
    A non-empty page with empty layout (no blocks, no error) → failed with a Page block."""
    usable = [b for b in res.blocks if b.bbox is not None]
    if usable:
        return "done", usable
    if not res.blocks and res.error is None:
        # No blocks and no error: blank page → done with no blocks; non-blank → failed with Page block
        if is_blank:
            return "done", []
        return "failed", [Block(PAGE_CATEGORY, "", (0, 0, size[0], size[1]))]
    return "failed", [Block(PAGE_CATEGORY, "", (0, 0, size[0], size[1]))]


def run_layout(state: BookState, ocr: PageOCR, work_dir: Path, out_dir: Path, figure_pad: int,
               guard: TransportGuard, log: Callable[[str], None] = _noop,
               webp_quality: int = 70) -> int:
    """Mark up all pages with status pending. Returns the number of pages processed."""
    pending = state.pages(layout_status="pending")
    images = PageImages(work_dir, {p.name: p.file for p in pending})
    done = 0
    for page in pending:
        if page.blank:
            state.set_layout(page.name, [], status="done", error="blank")
            done += 1
            continue
        img = images.get(page.name)
        t0 = time.monotonic()
        try:
            res = guard.call(ocr.ocr_page, img)
        except TransportFailed as e:
            state.set_page_error(page.name, f"transport: {e}")  # the page stays pending
            log(f"layout {page.name}: transport failure: {e}")
            guard.failure(page.name)
            continue
        guard.success()
        status, blocks = layout_blocks(res, img.size, is_blank=page.blank)
        # Add empty_layout error if layout is empty (for non-blank pages with no blocks and no error)
        layout_error = res.error
        if not blocks and layout_error is None and not page.blank:
            layout_error = "empty_layout"
        # Validate Picture blocks and filter out those with invalid bboxes.
        # figures and file names are indexed by position in filtered_blocks — ord in state.
        figures: dict[int, str] = {}
        bad_bbox_count = 0
        filtered_blocks = []
        for b in blocks:
            if b.category == "Picture":
                # Clamp bbox and skip Picture blocks with invalid bbox
                clamped = clamp_bbox(b.bbox, img.size)
                if clamped is None:
                    bad_bbox_count += 1
                    log(f"layout {page.name}: Picture block {len(filtered_blocks)} has invalid bbox, skipping")
                    continue
                rel = f"images/p{page.name}_fig{len(filtered_blocks)}.webp"
                try:
                    save_image(deskew_photo(img.crop(pad_box(clamped, img.size, figure_pad))),
                               out_dir / rel, quality=webp_quality)
                    figures[len(filtered_blocks)] = rel
                except Exception as e:
                    log(f"layout {page.name}: Picture block {len(filtered_blocks)} crop/save failed: {e}")
            filtered_blocks.append(b)
        if bad_bbox_count > 0:
            if layout_error:
                layout_error = f"{layout_error};bad_bbox:{bad_bbox_count}"
            else:
                layout_error = f"bad_bbox:{bad_bbox_count}"
        state.set_layout(page.name, filtered_blocks, status=status, error=layout_error, raw=res.raw,
                         seconds=res.seconds or time.monotonic() - t0, images=figures)
        log(f"layout {page.name}: {status}, {len(filtered_blocks)} blocks" + (f", {layout_error}" if layout_error else ""))
        done += 1
    return done
