"""Common interface of a book source (djvu/pdf)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PIL import Image

from techbookocr.ingest.djvu import DjvuDocument
from techbookocr.ingest.pdf import PdfDocument


class UnsupportedFormat(ValueError):
    pass


class BookSource(Protocol):
    page_count: int

    def render(self, index: int, max_dpi: int, min_dpi: int) -> tuple[Image.Image, int]: ...
    def close(self) -> None: ...
    # optional: page_rect(index) -> (w, h) in points; only for sources with vector geometry (PDF)
    def __enter__(self) -> "BookSource": ...
    def __exit__(self, *exc) -> None: ...


class _Djvu(DjvuDocument):
    def render(self, index: int, max_dpi: int = 600, min_dpi: int = 300) -> tuple[Image.Image, int]:
        return super().render(index, max_dpi=max_dpi)


def open_book(path: Path) -> BookSource:
    ext = Path(path).suffix.lower()
    if ext == ".djvu":
        return _Djvu(path)
    if ext == ".pdf":
        return PdfDocument(path)
    raise UnsupportedFormat(f"unsupported format: {path}")


def scan_count(path: Path) -> int | None:
    """Number of book frames without rendering (djvu from the header, pdf via PyMuPDF). Any failure -> None."""
    try:
        with open_book(Path(path)) as src:
            return int(src.page_count)
    except Exception:  # broken file, no libdjvulibre: for the forecast this means "unknown", not an error
        return None
