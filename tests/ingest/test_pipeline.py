import json

from techbookocr.config import RenderConfig
from techbookocr.ingest.pipeline import PageRef, ingest_book
from tests.ingest.test_spread import _spread, _text_page


class FakeSource:
    def __init__(self, images):
        self.images = images
        self.page_count = len(images)
        self.calls = 0

    def render(self, index, max_dpi=600, min_dpi=300):
        self.calls += 1
        return self.images[index], 300

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def test_ingest_splits_and_records(tmp_path, monkeypatch):
    spread, _ = _spread()
    src = FakeSource([_text_page(1100, 1600, 5), spread])
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    refs = ingest_book(tmp_path / "book.djvu", tmp_path / "work", RenderConfig(deskew=False))
    assert [r.name for r in refs] == ["0000", "0001L", "0001R"]
    for r in refs:
        assert (tmp_path / "work" / "pages" / r.file).exists()
    data = json.loads((tmp_path / "work" / "pages.json").read_text())
    assert [d["file"] for d in data] == ["0000.png", "0001L.png", "0001R.png"]


def test_ingest_is_idempotent(tmp_path, monkeypatch):
    src = FakeSource([_text_page(1100, 1600, 5), _text_page(1100, 1600, 6)])
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
    assert src.calls == 2
    refs = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
    assert src.calls == 2
    assert len(refs) == 2


def test_ingest_selected_scans(tmp_path, monkeypatch):
    src = FakeSource([_text_page(1100, 1600, i) for i in range(5)])
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    refs = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False), scans=[3, 1])
    assert [r.scan for r in refs] == [1, 3]


def test_pageref_name():
    assert PageRef(scan=7, side="R", file="0007R.png", dpi=300, skew=0.0).name == "0007R"


def test_deleted_png_retriggers_render(tmp_path, monkeypatch):
    src = FakeSource([_text_page(1100, 1600, 5), _text_page(1100, 1600, 6)])
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
    assert src.calls == 2
    (tmp_path / "w" / "pages" / "0000.png").unlink()
    refs = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
    assert src.calls == 3
    assert len(refs) == 2


def test_ingest_partial_then_different_scans(tmp_path, monkeypatch):
    src = FakeSource([_text_page(1100, 1600, i) for i in range(3)])
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    refs1 = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False), scans=[1])
    assert [r.scan for r in refs1] == [1]
    refs2 = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False), scans=[0])
    assert [r.scan for r in refs2] == [0]
    data = json.loads((tmp_path / "w" / "pages.json").read_text())
    assert [d["scan"] for d in data] == [0, 1]


def test_corrupt_pages_json_raises_valueerror(tmp_path, monkeypatch):
    src = FakeSource([_text_page(1100, 1600, 5)])
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
    (tmp_path / "w" / "pages.json").write_text("[truncated")
    try:
        ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "corrupt page index" in str(e)


def test_reingest_with_changed_render_config_rerenders(tmp_path, monkeypatch):
    spread, _ = _spread()
    src = FakeSource([spread])
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    refs = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
    assert [r.name for r in refs] == ["0000L", "0000R"]
    assert src.calls == 1
    refs = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False, split_spreads="never"))
    assert [r.name for r in refs] == ["0000"]
    assert src.calls == 2
    pages = tmp_path / "w" / "pages"
    assert sorted(p.name for p in pages.iterdir()) == ["0000.png"]
    data = json.loads((tmp_path / "w" / "pages.json").read_text())
    assert data[0]["render"]["split_spreads"] == "never"


def test_blank_flag_recorded(tmp_path, monkeypatch):
    src = FakeSource([_text_page(1100, 1600, 5)])
    src.last_render_blank = True
    monkeypatch.setattr("techbookocr.ingest.pipeline.open_book", lambda p: src)
    refs = ingest_book(tmp_path / "b.djvu", tmp_path / "w", RenderConfig(deskew=False))
    assert refs[0].blank is True
    assert json.loads((tmp_path / "w" / "pages.json").read_text())[0]["blank"] is True
