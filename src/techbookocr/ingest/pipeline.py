"""Book -> normalized page images."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from techbookocr.config import ConfigError, RenderConfig
from techbookocr.ingest.cleanup import crop_dark_borders, deskew
from techbookocr.ingest.source import BookSource, open_book
from techbookocr.ingest.spread import split_spread


@dataclass(frozen=True)
class PageRef:
    scan: int
    side: str
    file: str
    dpi: int
    skew: float
    render: dict | None = None  # effective RenderConfig the file was produced with
    blank: bool = False  # the source failed to render: a white page was substituted
    width: int = 0       # pixels at dpi; 0 means read from the file (the usual path)
    height: int = 0

    @property
    def name(self) -> str:
        return f"{self.scan:04d}{self.side}"


def ingest_page(src: BookSource, scan: int, pages_dir: Path, cfg: RenderConfig) -> list[PageRef]:
    img, dpi = src.render(scan, max_dpi=cfg.max_dpi, min_dpi=cfg.min_dpi)
    blank = bool(getattr(src, "last_render_blank", False))
    render = asdict(cfg)
    refs = []
    for side, part in split_spread(img, cfg.split_spreads):
        if cfg.crop_borders:
            part = crop_dark_borders(part)
        angle = 0.0
        if cfg.deskew:
            part, angle = deskew(part)
        ref = PageRef(scan=scan, side=side, file=f"{scan:04d}{side}.png", dpi=dpi, skew=angle, render=render, blank=blank)
        part.save(pages_dir / ref.file)
        refs.append(ref)
    return refs


def _load(index_path: Path) -> list[PageRef]:
    if not index_path.exists():
        return []
    try:
        return [PageRef(**d) for d in json.loads(index_path.read_text(encoding="utf-8"))]
    except json.JSONDecodeError as e:
        raise ConfigError(f"corrupt page index {index_path}: delete it to re-ingest") from e


def lazy_page_refs(src: BookSource, scans: Iterable[int], cfg: RenderConfig) -> dict[int, list[PageRef]]:
    """Page references without rasterizing, for born-digital PDFs with a text layer.

    Sizes are computed in the virtual pixel space of min_dpi: rect_points * dpi/72,
    so block coordinates and crops work as if the page had been rendered."""
    dpi = cfg.min_dpi
    refs: dict[int, list[PageRef]] = {}
    for scan in scans:
        w, h = src.page_rect(scan)
        refs[scan] = [PageRef(scan=scan, side="", file="", dpi=dpi, skew=0.0, render=asdict(cfg),
                              width=round(w * dpi / 72), height=round(h * dpi / 72))]
    return refs


def ingest_book(book: Path, work_dir: Path, cfg: RenderConfig, scans: Iterable[int] | None = None,
                lazy: bool = False) -> list[PageRef]:
    pages_dir = work_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    index_path = work_dir / "pages.json"
    done: dict[int, list[PageRef]] = {}
    for r in _load(index_path):
        done.setdefault(r.scan, []).append(r)
    with open_book(book) as src:
        wanted = sorted(set(scans)) if scans is not None else list(range(src.page_count))
        for scan in wanted:
            if scan in done:
                usable = all(((pages_dir / r.file).exists() if r.file else lazy)
                             and r.render == asdict(cfg) for r in done[scan])
                if usable:
                    continue
                for r in done[scan]:  # stale files (e.g. L/R after switching to "never")
                    if r.file:
                        (pages_dir / r.file).unlink(missing_ok=True)
            done[scan] = (lazy_page_refs(src, [scan], cfg)[scan] if lazy
                          else ingest_page(src, scan, pages_dir, cfg))
            all_refs = [r for s in sorted(done) for r in done[s]]
            tmp_path = index_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps([asdict(r) for r in all_refs], ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp_path, index_path)
    wanted_set = set(wanted)
    return [r for s in sorted(done) if s in wanted_set for r in done[s]]
