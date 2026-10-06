"""Deskew and trim dark margins of a scan."""
from __future__ import annotations

import numpy as np
from PIL import Image


def _ink(img: Image.Image, width: int = 1000) -> Image.Image:
    g = img.convert("L")
    if g.size[0] > width:
        g = g.resize((width, round(g.size[1] * width / g.size[0])))
    return g.point(lambda v: 255 if v < 128 else 0)


def _score(ink: Image.Image, angle: float) -> float:
    rows = np.asarray(ink.rotate(angle, fillcolor=0), dtype=np.float32).sum(axis=1)
    return float(rows.var())


def estimate_skew(img: Image.Image, max_angle: float = 3.0) -> float:
    ink = _ink(img)
    coarse = np.arange(-max_angle, max_angle + 1e-9, 0.5)
    best = max(coarse, key=lambda a: _score(ink, a))
    fine_start = max(best - 0.5, -max_angle)
    fine_end = min(best + 0.5, max_angle)
    fine = np.arange(fine_start, fine_end + 1e-9, 0.05)
    return round(float(max(fine, key=lambda a: _score(ink, a))), 2)


def deskew(img: Image.Image, min_angle: float = 0.15) -> tuple[Image.Image, float]:
    angle = estimate_skew(img)
    if abs(angle) < min_angle:
        return img, 0.0
    out = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor="white")
    return out, angle


def crop_dark_borders(img: Image.Image, dark: int = 80, frac: float = 0.6, max_side: float = 0.15) -> Image.Image:
    a = np.asarray(img.convert("L")) < dark
    h, w = a.shape
    row_dark, col_dark = a.mean(axis=1), a.mean(axis=0)

    def run(values: np.ndarray, limit: int) -> int:
        n = 0
        while n < limit and values[n] > frac:
            n += 1
        return n

    top = run(row_dark, int(h * max_side))
    bottom = run(row_dark[::-1], int(h * max_side))
    left = run(col_dark, int(w * max_side))
    right = run(col_dark[::-1], int(w * max_side))
    return img.crop((left, top, w - right, h - bottom))
