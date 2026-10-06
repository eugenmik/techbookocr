"""Find the spine and split a spread into two pages."""
from __future__ import annotations

import numpy as np
from PIL import Image

_SCALE = 4
_GUTTER_MAX_REL = 0.15
_MIN_INK = 0.01


def _column_transitions(img: Image.Image) -> tuple[np.ndarray, np.ndarray] | None:
    g = np.asarray(img.convert("L").reduce(_SCALE))
    p1, p95 = np.percentile(g, 1), np.percentile(g, 95)
    if p95 - p1 < 30:
        return None
    ink = (g < (p1 + p95) / 2).astype(np.int8)
    trans = np.abs(np.diff(ink, axis=0)).sum(axis=0).astype(float)
    k = max(3, ink.shape[1] // 100)
    smooth = np.convolve(trans, np.ones(k) / k, mode="same")
    return smooth, ink


def find_gutter(img: Image.Image) -> int | None:
    res = _column_transitions(img)
    if res is None:
        return None
    smooth, ink = res
    w = smooth.size
    text_level = np.percentile(smooth, 75)
    if text_level <= 0:
        return None

    low = smooth <= _GUTTER_MAX_REL * text_level
    interior_lo, interior_hi = w // 10, 9 * w // 10
    runs: list[tuple[int, int]] = []
    start = None
    for i in range(interior_hi + 1):
        is_low = interior_lo <= i < interior_hi and bool(low[i])
        if is_low and start is None:
            start = i
        elif not is_low and start is not None:
            if i - start >= 3:
                runs.append((start, i))
            start = None

    mid = [r for r in runs if w / 3 <= (r[0] + r[1]) / 2 <= 2 * w / 3]
    if not mid:
        return None
    cand = max(mid, key=lambda r: r[1] - r[0])
    cw = cand[1] - cand[0]
    others = [r[1] - r[0] for r in runs if r != cand]
    if not (cw >= 0.025 * w or all(cw >= 2 * o for o in others)):
        return None

    x = (cand[0] + cand[1]) // 2
    if ink[:, :x].mean() < _MIN_INK or ink[:, x:].mean() < _MIN_INK:
        return None
    return x * _SCALE


def split_spread(img: Image.Image, mode: str = "auto") -> list[tuple[str, Image.Image]]:
    if mode == "never":
        return [("", img)]
    w, h = img.size
    if mode == "auto" and w <= 1.1 * h:
        return [("", img)]
    x = find_gutter(img)
    if x is None:
        if mode != "always":
            return [("", img)]
        x = w // 2
    return [("L", img.crop((0, 0, x, h))), ("R", img.crop((x, 0, w, h)))]
