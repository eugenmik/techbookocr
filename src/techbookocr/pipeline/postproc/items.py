"""A book element after postprocessing — the input of the book.md assembly."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    id: int
    page: str
    ord: int
    category: str
    text: str
    image: str | None = None                            # Picture: crop path relative to out/<book>/
    sketches: list[dict] = field(default_factory=list)  # Table: [{"path", "bbox"}] in reading order
    text_b: str | None = None                           # Table: Chandra HTML — where <img> sit in the cells
    join_to: int | None = None                          # id of the previous page's paragraph that this one continues
    note: str | None = None                             # comment before the element ("continues: tabl. X")
    bbox: tuple[int, int, int, int] | None = None       # block frame on the page (for the reading order of floating blocks)
    spans: list[str] = field(default_factory=list)      # Table: merged cells, for quality.md
