import pytest

from techbookocr.ingest.source import UnsupportedFormat, open_book


def test_unsupported_extension(tmp_path):
    f = tmp_path / "x.epub"
    f.write_bytes(b"x")
    with pytest.raises(UnsupportedFormat):
        open_book(f)


def test_scan_count_pdf_and_bad_file(tmp_path):
    import pymupdf

    from techbookocr.ingest.source import scan_count

    pdf = tmp_path / "b.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    doc.save(pdf)
    assert scan_count(pdf) == 3
    bad = tmp_path / "x.djvu"
    bad.write_bytes(b"not a djvu")
    assert scan_count(bad) is None
    assert scan_count(tmp_path / "missing.pdf") is None


@pytest.mark.books
def test_open_djvu(vor_path):
    with open_book(vor_path) as src:
        assert src.page_count == 327
        img, dpi = src.render(60, max_dpi=600, min_dpi=300)
        assert dpi == 300 and img.size == (2256, 2886)
