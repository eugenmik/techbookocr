"""Block crops from a page: padding, upscaling to a line height, atomic write, page cache."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

Box = tuple[int, int, int, int]


def pad_box(bbox: Box, size: tuple[int, int], pad: int) -> Box:
    w, h = size
    x1, y1, x2, y2 = bbox
    return max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)


def line_height(img: Image.Image, min_run: int = 3) -> int | None:
    """Median height of text lines (runs of pixel rows with ink); None if no text is visible.

    Columns filled with ink almost over the whole height (> 90%: vertical table rules) are ignored."""
    ink = np.asarray(img.convert("L"), dtype=np.uint8) < 128
    if ink.size == 0:
        return None
    ink = ink[:, ink.mean(axis=0) <= 0.9]
    if ink.shape[1] == 0:
        return None
    rows = ink.sum(axis=1) > max(1, int(0.01 * ink.shape[1]))
    runs, n = [], 0
    for r in rows:
        if r:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    runs = [r for r in runs if r >= min_run]
    return int(np.median(runs)) if runs else None


def crop_block(page: Image.Image, bbox: Box, pad: int, min_line_px: int = 32, max_upscale: float = 4.0,
               max_pixels: int = 6_000_000, mask: tuple[Box, ...] = ()) -> Image.Image:
    """Block crop with padding; small text is upscaled to line height ≥ min_line_px (no more than max_upscale and max_pixels).

    Computes the final scale BEFORE any resize to avoid huge intermediate images."""
    box = pad_box(bbox, page.size, pad)
    crop = page.crop(box)
    if mask:  # areas of foreign blocks (table, figure) are painted white: the model must not read them
        crop = crop.copy()
        for x1, y1, x2, y2 in mask:
            crop.paste((255, 255, 255), (x1 - box[0], y1 - box[1], x2 - box[0], y2 - box[1]))
    h = line_height(crop)

    # Compute final scale (before any resize) to avoid huge intermediate images
    scale = 1.0
    if h is not None and h < min_line_px:
        scale = min(max_upscale, min_line_px / h)

    # Clamp scale by max_pixels constraint
    pixels = crop.width * crop.height
    if pixels > max_pixels or (scale * scale * pixels) > max_pixels:
        max_scale = (max_pixels / pixels) ** 0.5
        scale = min(scale, max_scale)

    # Single resize with final scale
    if scale != 1.0:
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS)

    return crop


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull of points (x, y), Andrew's monotone chain."""
    pts = np.unique(pts, axis=0)
    if len(pts) < 3:
        return pts

    def half(points):
        out: list = []
        for p in points:
            while len(out) >= 2 and _cross(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]
    return np.array(half(pts) + half(pts[::-1]))


def deskew_photo(img: Image.Image, min_angle: float = 0.5, max_angle: float = 8.0, min_fill: float = 0.97,
                 ink: int = 235) -> Image.Image:
    """Straighten a noticeably tilted photo: minimal rotated rectangle around non-empty pixels;
    rotate only if the convex hull fills it almost entirely (a rectangular photo, not an object on a white background or a sketch) and the tilt
    is in [min_angle, max_angle] degrees. Otherwise the original image unchanged."""
    mask = np.asarray(img.convert("L")) < ink
    if mask.sum() < 400:
        return img
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    edge = [(int(np.argmax(mask[y])), y) for y in rows] + [(mask.shape[1] - 1 - int(np.argmax(mask[y, ::-1])), y) for y in rows]
    edge += [(x, int(np.argmax(mask[:, x]))) for x in cols] + [(x, mask.shape[0] - 1 - int(np.argmax(mask[::-1, x]))) for x in cols]
    hull = _hull(np.array(edge, dtype=float))
    if len(hull) < 3:
        return img
    best = None
    for i in range(len(hull)):
        dx, dy = hull[(i + 1) % len(hull)] - hull[i]
        if dx == dy == 0:
            continue
        t = np.arctan2(dy, dx)
        c, s = np.cos(-t), np.sin(-t)
        r = hull @ np.array([[c, s], [-s, c]])
        area = np.ptp(r[:, 0]) * np.ptp(r[:, 1])
        if best is None or area < best[0]:
            best = (area, t)
    area, t = best
    deg = (np.degrees(t) + 45) % 90 - 45  # tilt of the rectangle side to the nearest axis
    x, y = hull[:, 0], hull[:, 1]
    hull_area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    # the photo outline is a rectangle (the hull fills it); an object on a white background or a sketch is not
    c, s_ = np.cos(-t), np.sin(-t)
    r = hull @ np.array([[c, s_], [-s_, c]])
    short = min(np.ptp(r[:, 0]), np.ptp(r[:, 1]))
    if not (min_angle <= abs(deg) <= max_angle) or area <= 0 or short < 40 or hull_area / area < min_fill:
        return img
    rot = img.convert("RGB").rotate(deg, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    m = np.asarray(rot.convert("L")) < ink
    ys, xs = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
    return rot.crop((int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1))


_WEBP_QUALITY = 70  # lossy q70 method=6: by measurements on diagrams/sketches the quality knee
                    # is ~q60 — q70 keeps SSIM≈0.996 on ink at −30% size vs q90


def save_image(img: Image.Image, path: Path, quality: int | None = None) -> None:
    """Atomic write (tmp + replace); format by extension: .webp is lossy WebP, otherwise PNG.
    On failure removes the .tmp."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        if path.suffix.lower() == ".webp":
            if img.mode not in ("RGB", "RGBA", "L", "LA"):
                img = img.convert("RGB")  # P/CMYK/1 — WebP cannot write these
            img.save(tmp, format="WEBP",
                     quality=_WEBP_QUALITY if quality is None else quality, method=6)
        else:
            img.save(tmp, format="PNG")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


class PageImages:
    """Book page images with a cache of the last opened one (blocks are traversed in page order)."""

    def __init__(self, work_dir: Path, files: dict[str, str]):
        self.work_dir, self.files = Path(work_dir), files
        self._name: str | None = None
        self._img: Image.Image | None = None

    def get(self, page: str) -> Image.Image:
        if page != self._name:
            with Image.open(self.work_dir / self.files[page]) as im:
                self._img = im.convert("RGB")
            self._name = page
        return self._img


class PdfPageImages(PageImages):
    """Same as PageImages.get, but pages without a PNG (file=="") are rendered from the PDF in its pixel
    space (the dpi at which width/height were recorded): crops of text-layer blocks."""

    def __init__(self, work_dir: Path, files: dict[str, str], pdf_path, pages) -> None:
        super().__init__(work_dir, files)
        import pymupdf
        self._doc = pymupdf.open(str(pdf_path))
        self._scan = {pg.name: pg.scan for pg in pages}
        self._dpi: dict[str, float] = {}
        for pg in pages:
            r = self._doc[pg.scan].rect
            self._dpi[pg.name] = pg.width / r.width * 72 if r.width else 300.0

    def get(self, page: str) -> Image.Image:
        if self.files.get(page):
            return super().get(page)
        if page != self._name:
            pix = self._doc[self._scan[page]].get_pixmap(dpi=round(self._dpi[page]), alpha=False)
            self._img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            self._name = page
        return self._img

    def close(self) -> None:
        self._doc.close()
