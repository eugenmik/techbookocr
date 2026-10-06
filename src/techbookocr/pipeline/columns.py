"""Table column boundaries from vertical rules and horizontal extents of values within a row."""
from __future__ import annotations

import numpy as np
from PIL import Image

from techbookocr.pipeline.crops import Box
from techbookocr.pipeline.sketches import _runs


def _rules(dense, max_rule_px: int) -> list[int]:
    """Midpoints of thin runs: a wide run is text/a figure, not a rule."""
    return [(a + b - 1) // 2 for a, b in _runs(dense) if b - a <= max_rule_px]


def _rule_axis(lines, min_ink: float, max_rule_px: int) -> list[int]:
    """Rules from the lines of an ink matrix: a line counts as a rule when one solid segment
    of ink covers at least min_ink of its length (several separate values do not
    count as a rule) and the run of such lines is thinner than max_rule_px."""
    size = lines.shape[1]
    dense = np.array([max((b - a for a, b in _runs(line)), default=0) >= min_ink * size
                      for line in lines])
    return _rules(dense, max_rule_px)


def column_rules(img: Image.Image, min_ink: float = 0.6, ink_level: int = 160,
                 max_rule_px: int = 6) -> list[int]:
    """x of vertical rules: pixel columns filled with ink for at least min_ink of the height.
    Adjacent columns are merged into one rule (its midpoint). No rules: empty list."""
    ink = np.asarray(img.convert("L"), dtype=np.uint8) < ink_level
    if ink.size == 0:
        return []
    return _rule_axis(ink.T, min_ink, max_rule_px)


def row_rules(img: Image.Image, min_ink: float = 0.6, ink_level: int = 160,
              max_rule_px: int = 6) -> list[int]:
    """y of horizontal rules: pixel rows filled with ink for at least min_ink of the width."""
    ink = np.asarray(img.convert("L"), dtype=np.uint8) < ink_level
    if ink.size == 0:
        return []
    return _rule_axis(ink, min_ink, max_rule_px)


def value_spans(img: Image.Image, rules: list[int], row_box: Box, ink_level: int = 160,
                gap_px: int = 12) -> list[tuple[int, int]]:
    """Extents (x1, x2) of ink groups in a row band, excluding the pixels of the rules themselves."""
    x1, y1, x2, y2 = row_box
    ink = np.asarray(img.convert("L").crop((x1, y1, x2, y2)), dtype=np.uint8) < ink_level
    if ink.size == 0:
        return []
    cols = ink.any(axis=0)
    for r in rules:
        for dx in (-2, -1, 0, 1, 2):
            if 0 <= r - x1 + dx < len(cols):
                cols[r - x1 + dx] = False
    out = []
    for a, b in _runs(cols):  # (a, b) is a run of filled columns, end exclusive
        if out and a - out[-1][1] <= gap_px:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(a + x1, b - 1 + x1) for a, b in out]  # x2 is the last column with ink, inclusive
