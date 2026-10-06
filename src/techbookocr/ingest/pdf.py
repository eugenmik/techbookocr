"""Render PDF via PyMuPDF, taking the scan's original resolution into account."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from PIL import Image


def native_dpi(page: fitz.Page) -> int | None:
    best = None
    for info in page.get_image_info():
        bbox = fitz.Rect(info["bbox"])
        if bbox.width <= 1:
            continue
        dpi = info["width"] / (bbox.width / 72)
        if best is None or dpi > best:
            best = dpi
    return round(best) if best else None


class PdfDocument:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._doc = fitz.open(self.path)
        self.page_count: int = self._doc.page_count

    def page_rect(self, index: int) -> tuple[float, float]:
        """Page size in points, for the virtual pixel space of lazy ingest."""
        r = self._doc[index].rect
        return r.width, r.height

    def render(self, index: int, max_dpi: int = 600, min_dpi: int = 300) -> tuple[Image.Image, int]:
        if not 0 <= index < self.page_count:
            raise IndexError(f"page {index} out of range 0..{self.page_count - 1}")
        page = self._doc[index]
        dpi = min(max(native_dpi(page) or min_dpi, min_dpi), max_dpi)
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), dpi

    def close(self) -> None:
        self._doc.close()

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
