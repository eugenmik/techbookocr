"""PDF text layer: born-digital probe and page status."""
from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image

from techbookocr.config import PipelineConfig
from techbookocr.models.types import Block
from techbookocr.pipeline.state import BookState, PageEntry
from techbookocr.pipeline.textlayer import (
    cell_text, extract_images, extract_tables, extract_text, font_roles,
    page_layer_status, probe_pdf, run_extract, table_confidence,
)


def _png_bytes(size=(32, 32), color=(128, 128, 128)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def make_test_pdf(pages: list[dict]) -> pymupdf.Document:
    """Synthetic PDF: pages are lists of {"text", "size", "rects"} | {"image": True}.

    text: a string or a list of strings (one per rect); rects are coordinates in points.
    image: a single raster image over the whole page.
    """
    doc = pymupdf.open()
    for spec in pages:
        page = doc.new_page(width=595, height=841)
        if spec.get("image"):
            page.insert_image(pymupdf.Rect(spec.get("rect") or page.rect),
                              stream=spec.get("stream") or _png_bytes())
        for (cx, cy, r) in spec.get("circles", []):  # vector figure (curves, not a ruling)
            page.draw_circle((cx, cy), r)
        parts = spec.get("parts") or [{"text": spec.get("text", ""), "size": spec.get("size", 11),
                                       "font": spec.get("font", "tiro"), "rects": spec.get("rects")}]
        for part in parts:
            texts = part["text"]
            if isinstance(texts, str):
                texts = [texts]
            rects = part.get("rects") or [(28, 60, 570, 800)] * len(texts)
            size = part.get("size", 11)
            step = size * 1.4
            for rect, text in zip(rects, texts):
                r = pymupdf.Rect(*rect)
                y = r.y0 + size
                while y < r.y1 and text:
                    page.insert_text((r.x0, y), text[:60], fontsize=size,
                                     fontname=part.get("font", "tiro"))
                    text = text[60:]
                    y += step
        for line in spec.get("runs", []):  # [(x, y), [(text, size, dy), ...]]: mixed spans in a line
            (x, y), runs = line
            for text, sz, dy in runs:
                page.insert_text((x, y + dy), text, fontsize=sz, fontname="tiro")
                x += pymupdf.get_text_length(text, fontsize=sz)
        for seg in spec.get("lines", []):  # [(x1,y1),(x2,y2)]: a table ruling
            page.draw_line(seg[0], seg[1], width=0.7)
        if spec.get("rotation"):
            page.set_rotation(spec["rotation"])
    return doc


def test_probe_born_digital():
    doc = make_test_pdf([{"text": "Some body text " * 20, "size": 11}] * 45)
    assert probe_pdf(doc, 40) is True


def test_probe_scanned():
    doc = make_test_pdf([{"image": True}] * 45)  # full-page raster, no text
    assert probe_pdf(doc, 40) is False


def test_probe_multicolumn_rejected():
    doc = make_test_pdf([{"text": ["col one " * 40, "col two " * 40], "size": 11,
                          "rects": [(28, 60, 290, 800), (305, 60, 570, 800)]}] * 45)
    assert probe_pdf(doc, 40) is False


def test_extract_text_and_headings():
    doc = make_test_pdf([{"parts": [
        {"text": "Chapter Title", "size": 24, "font": "tibo", "rects": [(28, 40, 570, 70)]},
        {"text": "Body text " * 30, "size": 11, "rects": [(28, 100, 570, 400)]},
        {"text": "Section Head", "size": 12, "font": "tibo", "rects": [(28, 500, 570, 520)]},
        {"text": "Fig. 1 Caption of figure", "size": 10, "rects": [(28, 600, 570, 620)]},
    ]}])
    roles = font_roles(doc, [0])
    blocks, _ = extract_text(doc[0], roles, 300, [])
    cats = [b.category for b in blocks]
    assert "Title" in cats and "Section-header" in cats and "Caption" in cats and "Text" in cats


def test_extract_subsup():
    doc = make_test_pdf([{"runs": [((100, 200), [("σ", 11, 0), ("m", 7, 2.5), (" is the mean", 11, 0)])]}])
    roles = font_roles(doc, [0])
    blocks, _ = extract_text(doc[0], roles, 300, [])
    joined = " ".join(b.text for b in blocks)
    assert "<sub>m</sub>" in joined


def test_reading_order():
    doc = make_test_pdf([{"parts": [
        {"text": "second para", "rects": [(28, 400, 570, 450)]},
        {"text": "first para", "rects": [(28, 100, 570, 150)]},
    ]}])
    roles = font_roles(doc, [0])
    blocks, _ = extract_text(doc[0], roles, 300, [])
    assert blocks[0].text.startswith("first para")
    assert blocks[1].text.startswith("second para")


def test_suspect_gap_flag():
    doc = make_test_pdf([{"runs": [((100, 200), [("Fm", 11, 0)]),
                                 ((130, 200), [("m", 11, 0)])]}])  # gap ~18 pt: a dropped glyph
    roles = font_roles(doc, [0])
    _, gaps = extract_text(doc[0], roles, 300, [])
    assert gaps >= 1


def test_exclude_zones():
    doc = make_test_pdf([{"parts": [
        {"text": "cell a1 cell b1", "rects": [(100, 300, 500, 400)]},
        {"text": "normal text", "rects": [(28, 600, 570, 650)]},
    ]}])
    roles = font_roles(doc, [0])
    blocks, _ = extract_text(doc[0], roles, 300, [pymupdf.Rect(100, 300, 500, 400)])
    joined = " ".join(b.text for b in blocks)
    assert "normal text" in joined and "cell a1" not in joined


def test_page_layer_status():
    doc = make_test_pdf([{"text": "word " * 100}, {"text": "a b c"}, {"image": True}, {}, {}])
    doc[4].set_rotation(90)
    doc[4].insert_text(pymupdf.Point(28, 60), "rotated text page words", fontsize=11)
    assert page_layer_status(doc[0]) == "layer"
    assert page_layer_status(doc[1]) == "layer"  # a rare but genuine page: not vision
    assert page_layer_status(doc[2]) == "vision"
    assert page_layer_status(doc[3]) == "blank"
    assert page_layer_status(doc[4]) == "vision"


def _grid_spec(rows: list[list[str]], x0=100, y0=200, cw=80, rh=25) -> dict:
    """A page with a ruled table: rows are cell values."""
    nr, nc = len(rows), max(len(r) for r in rows)
    lines = [((x0, y0 + i * rh), (x0 + nc * cw, y0 + i * rh)) for i in range(nr + 1)]
    lines += [((x0 + j * cw, y0), (x0 + j * cw, y0 + nr * rh)) for j in range(nc + 1)]
    runs = [((x0 + j * cw + 4, y0 + i * rh + rh * 0.72), [(v, 9, 0)])
            for i, row in enumerate(rows) for j, v in enumerate(row) if v]
    return {"runs": runs, "lines": lines}


def test_table_to_html_grid():
    doc = make_test_pdf([_grid_spec([["A", "B", "C"], ["1", "2", "3"], ["4", "5", "6"]])])
    roles = font_roles(doc, [0])
    tables = extract_tables(doc[0], roles, 300)
    assert len(tables) == 1
    blk, conf = tables[0]
    assert blk.category == "Table" and conf >= 0.7
    html = blk.text
    assert html.count("<tr") == 3
    for cell in ("A", "B", "C", "1", "2", "3", "4", "5", "6"):
        assert f">{cell}<" in html


def test_table_merged_cell_colspan():
    x0, y0, rh, cw = 100, 200, 25, 80
    lines = [((x0, y0 + i * rh), (x0 + 3 * cw, y0 + i * rh)) for i in range(3)]
    lines += [((x0, y0), (x0, y0 + 2 * rh)), ((x0 + 3 * cw, y0), (x0 + 3 * cw, y0 + 2 * rh)),
              ((x0 + cw, y0 + rh), (x0 + cw, y0 + 2 * rh)),      # bottom: both borders
              ((x0 + 2 * cw, y0 + rh), (x0 + 2 * cw, y0 + 2 * rh)),
              ((x0 + 2 * cw, y0), (x0 + 2 * cw, y0 + rh))]       # top: cell 0+1 is merged
    runs = [((x0 + 40, y0 + rh * 0.72), [("AB", 9, 0)]),
            ((x0 + 2 * cw + 4, y0 + rh * 0.72), [("C", 9, 0)])]
    runs += [((x0 + j * cw + 4, y0 + rh + rh * 0.72), [(v, 9, 0)])
             for j, v in enumerate(("1", "2", "3"))]
    doc = make_test_pdf([{"runs": runs, "lines": lines}])
    tables = extract_tables(doc[0], font_roles(doc, [0]), 300)
    blk, _ = tables[0]
    assert 'colspan="2"' in blk.text and ">AB<" in blk.text


def test_table_confidence_flags_irregular():
    doc = make_test_pdf([_grid_spec([["A", "", ""], ["", "", ""], ["", "", "9"]])])
    tables = extract_tables(doc[0], font_roles(doc, [0]), 300)
    if not tables:
        pytest.skip("find_tables не нашёл пустую сетку — проверяем на реальной книге")
    assert tables[0][1] < 0.7


def test_table_zone_removed_from_text():
    spec = _grid_spec([["A", "B"], ["1", "2"]], y0=300)
    spec["parts"] = [{"text": "Table 1\nValues", "size": 10, "rects": [(100, 260, 500, 295)]}]
    doc = make_test_pdf([spec])
    roles = font_roles(doc, [0])
    tables = extract_tables(doc[0], roles, 300)
    blocks, _ = extract_text(doc[0], roles, 300, [pymupdf.Rect(t[0].bbox) / (300 / 72)
                                                  for t in tables])
    joined = " ".join(b.text for b in blocks)
    assert "Table 1" in joined and ">A<" not in f"<{joined}>"


def test_table_cell_subsup():
    spec = _grid_spec([["x", "b"], ["y", "c"]], cw=60)
    spec["runs"][0] = ((104, 218), [("x", 9, 0), ("2", 6, 1.5)])
    doc = make_test_pdf([spec])
    tables = extract_tables(doc[0], font_roles(doc, [0]), 300)
    blk, _ = tables[0]
    assert "<sub>2</sub>" in blk.text


def test_cell_text_lines():
    doc = make_test_pdf([{"runs": [((100, 200), [("line one", 9, 0)]),
                                   ((100, 215), [("line two", 9, 0)])]}])
    txt = cell_text(doc[0], pymupdf.Rect(90, 185, 200, 225))
    assert "line one" in txt and "line two" in txt


def test_extract_raster_image(tmp_path):
    doc = make_test_pdf([{"image": True, "rect": (100, 200, 300, 400)}])
    pics, paths = extract_images(doc[0], doc, tmp_path, "0000", 300, 8, [])
    assert len(pics) == 1 and pics[0].category == "Picture"
    rel = paths[0]
    assert rel.startswith("images/p0000") and (tmp_path / rel).exists()


def test_tiny_image_skipped(tmp_path):
    doc = make_test_pdf([{"image": True, "rect": (100, 200, 110, 210)}])
    pics, _ = extract_images(doc[0], doc, tmp_path, "0000", 300, 8, [])
    assert pics == []


def test_vector_clip_rendered(tmp_path):
    doc = make_test_pdf([{"circles": [(200, 300, 80)]}])
    pics, paths = extract_images(doc[0], doc, tmp_path, "0000", 300, 8, [])
    assert len(pics) == 1
    assert (tmp_path / paths[0]).exists()


def test_rules_cluster_not_picture(tmp_path):
    doc = make_test_pdf([_grid_spec([["A", "B"], ["1", "2"]])])
    pics, _ = extract_images(doc[0], doc, tmp_path, "0000", 300, 8, [])
    assert pics == []


def _book_state(tmp_path, doc: pymupdf.Document, dpi=300) -> BookState:
    pdf_path = tmp_path / "book.pdf"
    doc.save(pdf_path)
    st = BookState(tmp_path / "work" / "state.sqlite")
    entries = [PageEntry(name=f"{i:04d}", idx=i, scan=i, side="", file="",
                         width=round(doc[i].rect.width * dpi / 72),
                         height=round(doc[i].rect.height * dpi / 72))
               for i in range(doc.page_count)]
    st.add_pages(entries)
    return st


def test_run_extract_hybrid(tmp_path):
    doc = make_test_pdf([
        {"parts": [{"text": "Body text " * 30, "size": 11, "rects": [(28, 100, 570, 300)]}],
         **_grid_spec([["A", "B"], ["1", "2"]], y0=400)},
        {"image": True},
        {},
    ])
    st = _book_state(tmp_path, doc)
    p = PipelineConfig()
    done = run_extract(st, tmp_path / "book.pdf", tmp_path / "work", tmp_path, p, lambda m: None)
    assert done == 2                                        # layer + empty, vision untouched
    p0, p1, p2 = (st.page(f"{i:04d}") for i in range(3))
    assert p0.layout_status == "done" and p1.layout_status == "pending"
    assert p2.layout_status == "done" and p2.layout_error == "blank"
    blocks = st.blocks("0000")
    assert blocks and all(b.origin == "layer" for b in blocks)
    cats = [b.category for b in blocks]
    assert "Text" in cats and "Table" in cats
    for b in blocks:
        if b.category == "Text":
            assert b.final == b.text_a and b.final_source == "layer"
            assert b.consensus_status == "done" and b.arbiter_status == "skipped"
    tab = next(b for b in blocks if b.category == "Table")
    if tab.consensus_status == "pending":                   # table is marked -> to the arbiter
        assert tab.arbiter_status == "skipped"              # until consensus has run
    stats = st.get_meta("extract:stats")
    assert stats and "layer_pages" in stats


def test_run_extract_low_conf_table_to_arbiter(tmp_path):
    spec = _grid_spec([["A", "", ""], ["", "", ""], ["", "", "9"]])
    doc = make_test_pdf([spec])
    st = _book_state(tmp_path, doc)
    run_extract(st, tmp_path / "book.pdf", tmp_path / "work", tmp_path,
                PipelineConfig(), lambda m: None)
    tab = next((b for b in st.blocks("0000") if b.category == "Table"), None)
    if tab is None:
        pytest.skip("таблица не обнаружена — арбитраж нечего проверять")
    assert tab.consensus_status == "pending"                # below the threshold -> consensus/arbiter
    assert tab.final is None


def test_state_origin_column(tmp_path):
    st = BookState(tmp_path / "w" / "state.sqlite")
    st.add_pages([PageEntry(name="0000", idx=0, scan=0, side="", file="x", width=1, height=1)])
    st.set_layout("0000", [], status="done")
    blk = st.blocks("0000")
    st.set_layout("0000", [Block("Text", "hi", (0, 0, 10, 10))], status="done")
    blk = st.blocks("0000")[0]
    assert blk.origin == "dots"                             # insert without origin -> dots
    st.update_block(blk.id, origin="layer")
    assert st.blocks("0000")[0].origin == "layer"
    st.close()
    st2 = BookState(tmp_path / "w" / "state.sqlite")        # reopening: the migration is idempotent
    assert st2.blocks("0000")[0].origin == "layer"


# --- golden: the real ASM Handbook (books marker) ---

@pytest.mark.books
def test_golden_asm_probe(asm_path):
    """A 2571-page born-digital PDF is detected by the auto probe."""
    doc = pymupdf.open(asm_path)
    assert probe_pdf(doc, 40) is True


@pytest.mark.books
def test_golden_asm_figure_and_caption(asm_path, tmp_path):
    """P. 150: the embedded raster "Fig. 1 A space lattice" -> a Picture block + file, the caption stays text."""
    doc = pymupdf.open(asm_path)
    page = doc[150]
    roles = font_roles(doc, list(range(140, 161)))
    pics, paths = extract_images(page, doc, tmp_path, "0150", 300, 8, [])
    assert pics and pics[0].category == "Picture"
    assert (tmp_path / paths[0]).stat().st_size > 1000
    blocks, _ = extract_text(page, roles, 300, [])
    assert any("Fig. 1" in b.text for b in blocks)


@pytest.mark.books
def test_golden_asm_lattice_table(asm_path):
    """P. 156, Table 3: an 18x10 grid, the "Lattice parameters" header on colspan=3, text-layer cells."""
    doc = pymupdf.open(asm_path)
    roles = font_roles(doc, list(range(150, 161)))
    tables = extract_tables(doc[156], roles, 300)
    assert tables and tables[0][1] < 0.7   # Fm3-barm -> Fm m: dropped glyphs -> gaps -> to the arbiter
    html = tables[0][0].text
    assert 'colspan="3"' in html           # "Lattice parameters (b), nm" above a/b/c
    assert "0.5311" in html and "cF4" in html and "Fm" in html


@pytest.mark.books
def test_golden_asm_subscript(asm_path):
    """P. 301: "sigma_m is the mean..." is a 7-pt span inside an 11-pt line -> sigma<sub>m</sub>."""
    doc = pymupdf.open(asm_path)
    roles = font_roles(doc, list(range(295, 311)))
    blocks, _ = extract_text(doc[301], roles, 300, [])
    assert any("σ<sub>m</sub>" in b.text for b in blocks)


def test_hidden_ocr_scan_is_vision():
    """A scan with a hidden OCR layer: the raster covers the page -> vision, not layer."""
    doc = make_test_pdf([{"image": True,
                         "parts": [{"text": "ocr text " * 30, "size": 11,
                                    "rects": [(28, 60, 570, 700)]}]}])
    assert page_layer_status(doc[0]) == "vision"


def test_probe_page_failure_not_fatal(monkeypatch):
    """An exception on one probe page does not break the whole check."""
    from techbookocr.pipeline import textlayer

    doc = make_test_pdf([{"text": "T " * 200, "size": 11}] * 4)
    real = textlayer.page_layer_status
    calls = [0]
    def flaky(page):
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError("broken page")
        return real(page)
    monkeypatch.setattr(textlayer, "page_layer_status", flaky)
    assert probe_pdf(doc, 4) is True          # 3 layer + 1 broken -> the book is born-digital


def test_raster_inside_table_not_picture(tmp_path):
    """A raster inside a table zone does not become a separate Picture block."""
    spec = _grid_spec([["A", "B"], ["1", "2"]], x0=50, y0=70, cw=125, rh=65)
    spec["image"] = True
    spec["rect"] = (55, 75, 165, 130)             # inside the first cell
    doc = make_test_pdf([spec])
    roles = font_roles(doc, [0])
    tables = extract_tables(doc[0], roles, 300)
    assert tables                                  # table found: the picture is in its zone
    exclude = [pymupdf.Rect(b.bbox) / (300 / 72) for b, _ in tables]
    pics, _ = extract_images(doc[0], doc, tmp_path, "0000", 300, 8, exclude)
    assert pics == []                              # not a separate picture, part of the table
