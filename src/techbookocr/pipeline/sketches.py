"""The sketches stage: sketches and drawings inside table cells (PP-DocLayoutV3 on a table crop)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from techbookocr.eval.figures import in_table, iou
from techbookocr.models.doclayout import Region
from techbookocr.pipeline.crops import Box, PageImages, deskew_photo, pad_box, save_image
from techbookocr.pipeline.state import BookState
from techbookocr.pipeline.transport import TransportFailed, TransportGuard

SPLIT_MIN_WIDTH = 0.6
SKETCH_LABELS = frozenset({"image", "chart", "figure"})


def _noop(msg: str) -> None:
    pass


def reading_order(boxes: list[Box]) -> list[Box]:
    """Rows top to bottom (a frame belongs to a row if its center is above the row bottom), left to right within a row."""
    rows: list[list[Box]] = []
    for b in sorted(boxes, key=lambda b: (b[1], b[0])):
        cy = (b[1] + b[3]) / 2
        if rows and cy <= max(x[3] for x in rows[-1]):
            rows[-1].append(b)
        else:
            rows.append([b])
    return [b for row in rows for b in sorted(row, key=lambda b: b[0])]


def pick_sketches(regions: list[Region], size: tuple[int, int], threshold: float,
                  min_area: float = 0.002, max_area: float = 0.6) -> list[Box]:
    """Graphics areas: label from SKETCH_LABELS, confidence ≥ threshold, area as a fraction of the crop
    in [min_area, max_area]; of overlapping ones (IoU > 0.5) the more confident remains. Reading order."""
    area = size[0] * size[1]
    cands = sorted((r for r in regions if r.label in SKETCH_LABELS and r.score >= threshold
                    and min_area <= (r.bbox[2] - r.bbox[0]) * (r.bbox[3] - r.bbox[1]) / area <= max_area),
                   key=lambda r: -r.score)
    kept: list[Box] = []
    for r in cands:
        if all(iou(r.bbox, k) <= 0.5 for k in kept):
            kept.append(r.bbox)
    return reading_order(kept)


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Runs of consecutive True: [(start, end exclusive)]."""
    out, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(flags)))
    return out


def split_by_ink_gaps(img: Image.Image, box: Box, gap_frac: float = 0.08, min_gap_px: int = 30,
                      min_part_px: int = 40, ink_level: int = 200, depth: int = 3) -> list[Box]:
    """Split a merged detector frame at clean gaps: bands without ink wider than max(min_gap_px, gap_frac·side)
    (first vertically, then horizontally inside each part). Parts smaller than min_part_px on either side
    do not form a split. Conservative: a frame without clear gaps is returned as is."""
    x1, y1, x2, y2 = box
    ink = np.asarray(img.convert("L").crop(box), dtype=np.uint8) < ink_level
    if ink.size == 0 or not ink.any():
        return [box]

    def cut(mask: np.ndarray, ox: int, oy: int, level: int) -> list[Box]:
        h, w = mask.shape
        if level == 0 or h == 0 or w == 0:
            return [(ox, oy, ox + w, oy + h)]
        for axis in (1, 0):  # 1: row bands (split vertically), 0: column bands
            side = h if axis == 1 else w
            profile = mask.sum(axis=axis) > 0
            parts = _runs(profile)  # pieces with ink
            if len(parts) < 2:
                continue
            need = max(min_gap_px, gap_frac * side)
            groups, cur = [], [parts[0]]
            for prev, nxt in zip(parts, parts[1:]):
                if nxt[0] - prev[1] >= need:
                    groups.append(cur)
                    cur = []
                cur.append(nxt)
            groups.append(cur)
            if len(groups) < 2:
                continue
            spans = [(g[0][0], g[-1][1]) for g in groups]
            if any(b - a < min_part_px for a, b in spans):
                continue
            out: list[Box] = []
            for a, b in spans:
                sub = mask[a:b, :] if axis == 1 else mask[:, a:b]
                out += cut(sub, ox + (0 if axis == 1 else a), oy + (a if axis == 1 else 0), level - 1)
            return out
        # without a split — a tight frame around the ink
        ys, xs = np.nonzero(mask)
        return [(ox + int(xs.min()), oy + int(ys.min()), ox + int(xs.max()) + 1, oy + int(ys.max()) + 1)]

    parts = cut(ink, x1, y1, depth)
    return parts if len(parts) > 1 else [box]


MIN_SKETCH_HEIGHT = 0.025  # fraction of page height: below it is a text line (Voronin p. 23, 265: "0,3" as a figure)


def drop_text_sized(boxes: list[Box], page_height: int, min_height: float = MIN_SKETCH_HEIGHT) -> list[Box]:
    """Drop areas one text line high: the real sketches of the reference are from 4% of the page height."""
    return [b for b in boxes if b[3] - b[1] >= min_height * page_height]


def run_sketches(state: BookState, detector, work_dir: Path, out_dir: Path, cfg, guard: TransportGuard,
                 log: Callable[[str], None] = _noop) -> int:
    """Sketches in all tables with status pending. cfg is PipelineConfig (crop_pad, figure_pad, sketch_threshold)."""
    pending = state.pending_blocks("sketches")
    images = PageImages(work_dir, {p.name: p.file for p in state.pages()})
    done = 0
    for blk in pending:
        if blk.bbox is None:
            state.update_block(blk.id, sketches_status="skipped")
            continue
        img = images.get(blk.page)
        box = pad_box(blk.bbox, img.size, cfg.crop_pad)
        try:
            regions, error = guard.call(detector.detect, img.crop(box))
        except TransportFailed as e:
            state.update_block(blk.id, sketches_error=f"transport: {e}")  # stays pending
            guard.failure(blk.id)
            continue
        guard.success()
        if error is not None:
            state.update_block(blk.id, sketches_status="failed", sketches_error=error)
            continue
        size = (box[2] - box[0], box[3] - box[1])
        found = []
        for x1, y1, x2, y2 in pick_sketches(regions, size, cfg.sketch_threshold):
            region = (x1 + box[0], y1 + box[1], x2 + box[0], y2 + box[1])
            # merged detector frame (gir-0150R) → separate sketches; split only wide ones (> 60% of the table crop)
            found += split_by_ink_gaps(img, region) if x2 - x1 > SPLIT_MIN_WIDTH * size[0] else [region]
        kept_boxes = drop_text_sized(found, img.size[1])
        if len(kept_boxes) < len(found):
            log(f"sketches {blk.page}/{blk.ord}: dropped {len(found) - len(kept_boxes)} text-sized")
        found = kept_boxes
        # layout Picture blocks centered inside the table are also sketches of this table
        pictures = [b for b in state.blocks(blk.page) if b.category == "Picture" and b.bbox is not None
                    and b.parent is None and in_table(b.bbox, [blk.bbox])]
        for p in pictures:
            if all(iou(p.bbox, f) <= 0.5 for f in found):
                found.append(p.bbox)
        sketches = []
        for n, b in enumerate(reading_order(found), 1):
            rel = f"images/p{blk.page}_tab{blk.ord}_cell{n}.webp"
            save_image(deskew_photo(img.crop(pad_box(b, img.size, cfg.figure_pad))),
                       out_dir / rel, quality=cfg.webp_quality)
            sketches.append({"path": rel, "bbox": list(b)})
        with state.transaction():
            for p in pictures:
                state.update_block(p.id, parent=blk.id)
            state.update_block(blk.id, sketches=sketches, sketches_status="done")
        log(f"sketches {blk.page}/{blk.ord}: {len(sketches)}")
        done += 1
    return done
