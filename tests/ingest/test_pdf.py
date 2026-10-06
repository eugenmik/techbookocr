from pathlib import Path

import fitz
from PIL import Image

from techbookocr.ingest.pdf import PdfDocument


def _make_scan_pdf(path: Path, px_w: int, inches_w: float) -> None:
    img = Image.new("RGB", (px_w, int(px_w * 1.4)), "white")
    img_path = path.with_suffix(".png")
    img.save(img_path)
    doc = fitz.open()
    page = doc.new_page(width=inches_w * 72, height=inches_w * 1.4 * 72)
    page.insert_image(page.rect, filename=str(img_path))
    doc.save(path)


def test_low_dpi_scan_rendered_at_min(tmp_path):
    p = tmp_path / "a.pdf"
    _make_scan_pdf(p, px_w=1000, inches_w=5)  # 200 dpi
    with PdfDocument(p) as d:
        assert d.page_count == 1
        img, dpi = d.render(0)
    assert dpi == 300
    assert abs(img.size[0] - 1500) <= 2


def test_high_dpi_scan_rendered_native(tmp_path):
    p = tmp_path / "b.pdf"
    _make_scan_pdf(p, px_w=2000, inches_w=5)  # 400 dpi
    with PdfDocument(p) as d:
        img, dpi = d.render(0)
    assert dpi == 400


def test_dpi_capped_at_max(tmp_path):
    p = tmp_path / "c.pdf"
    _make_scan_pdf(p, px_w=4000, inches_w=5)  # 800 dpi
    with PdfDocument(p) as d:
        _, dpi = d.render(0, max_dpi=600)
    assert dpi == 600


def test_out_of_range(tmp_path):
    p = tmp_path / "d.pdf"
    _make_scan_pdf(p, px_w=500, inches_w=5)
    import pytest

    with PdfDocument(p) as d, pytest.raises(IndexError):
        d.render(1)
