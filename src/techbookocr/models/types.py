"""Common OCR result types."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

CATEGORIES = (
    "Title", "Section-header", "Text", "List-item", "Table", "Formula",
    "Picture", "Caption", "Footnote", "Page-header", "Page-footer",
)


@dataclass
class Block:
    category: str
    text: str
    bbox: tuple[int, int, int, int] | None = None
    order: int = 0


@dataclass
class PageResult:
    markdown: str
    blocks: list[Block] = field(default_factory=list)
    raw: str = ""
    seconds: float = 0.0
    error: str | None = None


class PageOCR(Protocol):
    name: str

    def ocr_page(self, image: Image.Image) -> PageResult: ...

    def close(self) -> None: ...


def clamp_bbox(b, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """Round and clamp a box to [0,w]x[0,h]; None for non-numeric, infinite, and empty/inverted boxes."""
    try:
        vals = [float(v) for v in b[:4]]
        if len(vals) != 4 or not all(math.isfinite(v) for v in vals):
            return None
        w, h = size
        x1, y1, x2, y2 = (round(v) for v in vals)
    except (TypeError, ValueError, OverflowError):
        return None
    x1, x2 = max(0, min(w, x1)), max(0, min(w, x2))
    y1, y2 = max(0, min(h, y1)), max(0, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


BLOCK_KINDS = ("text", "title", "caption", "footnote", "list", "formula", "table", "page")


@dataclass
class BlockResult:
    text: str
    raw: str = ""
    seconds: float = 0.0
    error: str | None = None


class BlockOCR(Protocol):
    name: str

    def ocr_block(self, image: Image.Image, kind: str) -> BlockResult: ...

    def close(self) -> None: ...


class PromptVLM(Protocol):
    name: str
    vision: bool

    def ask(self, image: Image.Image, prompt: str, *, max_tokens: int | None = None) -> BlockResult: ...

    def close(self) -> None: ...
