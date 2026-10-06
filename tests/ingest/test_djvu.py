import pytest

from techbookocr.ingest.djvu import DjvuDocument, DjvuError

pytestmark = pytest.mark.books


def test_page_count_and_render(saf_path):
    with DjvuDocument(saf_path) as doc:
        assert doc.page_count == 159
        img, dpi = doc.render(100)
    assert img.mode == "RGB"
    assert dpi == 300
    assert img.size == (3315, 2464)


def test_render_downscales_above_max_dpi(saf_path):
    with DjvuDocument(saf_path) as doc:
        img, dpi = doc.render(100, max_dpi=150)
    assert dpi == 150
    assert abs(img.size[0] - 3315 // 2) <= 1


def test_out_of_range_raises_immediately(saf_path):
    with DjvuDocument(saf_path) as doc:
        with pytest.raises(IndexError):
            doc.render(doc.page_count)
        with pytest.raises(IndexError):
            doc.render(-1)


def test_not_a_djvu_raises(tmp_path):
    bad = tmp_path / "bad.djvu"
    bad.write_bytes(b"this is not a djvu file" * 100)
    with pytest.raises(DjvuError):
        DjvuDocument(bad)


def test_falsy_page_render_warns_and_returns_white(monkeypatch, caplog):
    import logging
    from unittest.mock import MagicMock

    from techbookocr.ingest import djvu

    lib = MagicMock()
    lib.ddjvu_document_create_by_filename_utf8.return_value = 1
    lib.ddjvu_job_status.return_value = djvu._JOB_OK
    lib.ddjvu_document_get_pagenum.return_value = 5
    lib.ddjvu_page_create_by_pageno.return_value = 1
    lib.ddjvu_page_get_width.return_value = 10
    lib.ddjvu_page_get_height.return_value = 12
    lib.ddjvu_page_get_resolution.return_value = 300
    lib.ddjvu_page_render.return_value = 0
    monkeypatch.setattr(djvu, "_L", lambda: lib)
    doc = djvu.DjvuDocument("x.djvu")
    with caplog.at_level(logging.WARNING, logger="techbookocr.ingest"):
        img, dpi = doc.render(3)
    assert img.size == (10, 12) and doc.last_render_blank
    assert "page 3" in caplog.text
