"""Lazy ingest: pages of a born-digital PDF are not rasterized."""
import json

import pytest

from techbookocr.config import RenderConfig
from techbookocr.ingest.pipeline import ingest_book


class LazySource:
    def __init__(self, rects):
        self.rects = rects
        self.page_count = len(rects)
        self.calls = 0

    def render(self, index, max_dpi=600, min_dpi=300):
        self.calls += 1
        raise AssertionError("lazy ingest не должен растрировать")

    def page_rect(self, index):
        return self.rects[index]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def test_lazy_ingest_writes_no_png(tmp_path, monkeypatch):
    src = LazySource([(595.0, 841.0)] * 3)
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    refs = ingest_book(tmp_path / "book.pdf", tmp_path / "work", RenderConfig(deskew=False), lazy=True)
    assert [r.name for r in refs] == ["0000", "0001", "0002"]
    assert all(r.file == "" for r in refs)
    assert refs[0].width == int(595 * 300 / 72)
    assert refs[0].height == int(841 * 300 / 72)
    assert list((tmp_path / "work" / "pages").glob("*.png")) == []
    data = json.loads((tmp_path / "work" / "pages.json").read_text())
    assert [d["file"] for d in data] == ["", "", ""]


def test_lazy_ingest_resumes(tmp_path, monkeypatch):
    src = LazySource([(595.0, 841.0)] * 2)
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    ingest_book(tmp_path / "b.pdf", tmp_path / "w", RenderConfig(deskew=False), lazy=True)
    refs = ingest_book(tmp_path / "b.pdf", tmp_path / "w", RenderConfig(deskew=False), lazy=True)
    assert len(refs) == 2


def test_normal_ingest_unchanged(tmp_path, monkeypatch):
    """lazy=False is the old behavior: render and files."""
    from tests.ingest.test_pipeline import FakeSource
    from tests.ingest.test_spread import _text_page
    src = FakeSource([_text_page(1100, 1600, 5)])
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    refs = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
    assert refs[0].file == "0000.png"
    assert (tmp_path / "w" / "pages" / "0000.png").exists()
