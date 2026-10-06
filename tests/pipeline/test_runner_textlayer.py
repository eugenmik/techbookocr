"""run_pages with a text layer: a text pass without models, --models finishes pending."""
from __future__ import annotations

import json

import pymupdf

from techbookocr.config import Config, ModelSpec, PipelineConfig
from techbookocr.pipeline.crops import PdfPageImages
from techbookocr.pipeline.runner import RunOptions, run_pages
from techbookocr.pipeline.state import BookState, PageEntry
from tests.pipeline.fakes import Servers, fake_adapters, fake_deps
from tests.pipeline.test_textlayer import _grid_spec, make_test_pdf

KEYS = ("dots_mocr", "hunyuan", "chandra2", "qwen9b_arbiter")
MODELS = {k: ModelSpec(key=k, adapter=k, image="img", model=k) for k in KEYS}
CFG = Config(models=MODELS, pipeline=PipelineConfig())


def _lazy_entries(doc: pymupdf.Document, dpi: int = 300) -> list[PageEntry]:
    return [PageEntry(name=f"{i:04d}", idx=i, scan=i, side="", file="",
                      width=round(doc[i].rect.width * dpi / 72),
                      height=round(doc[i].rect.height * dpi / 72))
            for i in range(doc.page_count)]


def _pdf(tmp_path, pages) -> str:
    doc = make_test_pdf(pages)
    path = tmp_path / "book.pdf"
    doc.save(path)
    return str(path)


def test_textlayer_run_skips_models(tmp_path):
    src = _pdf(tmp_path, [
        {"parts": [{"text": "Body text " * 30, "size": 11, "rects": [(28, 100, 570, 400)]}]},
        {"image": True},
    ])
    servers = Servers()
    out = run_pages(_lazy_entries(pymupdf.open(src)), tmp_path / "out", CFG,
                    RunOptions(models=False), book_name="Книга", source=src,
                    textlayer=True, **fake_deps(servers, fake_adapters()))
    assert servers.started == []                          # no model was started
    md = (out / "book.md").read_text(encoding="utf-8")
    assert "Body text" in md
    st = BookState(out / "work" / "state.sqlite")
    assert st.page("0000").layout_status == "done"
    assert st.page("0001").layout_status == "pending"     # vision page waits for --models
    st.close()


def test_models_flag_runs_pending(tmp_path):
    src = _pdf(tmp_path, [
        {"parts": [{"text": "Body text " * 30, "size": 11, "rects": [(28, 100, 570, 400)]}]},
        {"image": True},
    ])
    servers = Servers()
    out = run_pages(_lazy_entries(pymupdf.open(src)), tmp_path / "out", CFG,
                    RunOptions(models=True), book_name="Книга", source=src,
                    textlayer=True, **fake_deps(servers, fake_adapters()))
    st = BookState(out / "work" / "state.sqlite")
    assert st.page("0001").layout_status == "done"        # vision page was laid out by the model
    assert (tmp_path / "out" / "work" / "pages" / "0001.png").exists()
    st.close()
    assert "dots_mocr" in servers.started and "qwen9b_arbiter" in servers.started


def test_models_flag_noop_on_vision_book(tmp_path):
    from tests.pipeline.fakes import page_png
    page_png(tmp_path / "out" / "work" / "pages" / "0001.png")
    entries = [PageEntry(name="0001", idx=0, scan=0, side="", file="pages/0001.png",
                         width=1000, height=1400)]
    servers = Servers()
    out = run_pages(entries, tmp_path / "out", CFG, RunOptions(models=True),
                    book_name="Книга", source="b.djvu", textlayer=False,
                    **fake_deps(servers, fake_adapters()))
    assert servers.started[0] == "dots_mocr"              # regular flow, the flag is ignored
    assert (out / "book.md").exists()


def test_pending_table_renders_geometry_in_pass1(tmp_path):
    spec = _grid_spec([["A", "", ""], ["", "", ""], ["", "", "9"]])
    src = _pdf(tmp_path, [spec])
    out = run_pages(_lazy_entries(pymupdf.open(src)), tmp_path / "out", CFG,
                    RunOptions(models=False), book_name="Книга", source=src,
                    textlayer=True, **fake_deps(Servers(), fake_adapters()))
    st = BookState(out / "work" / "state.sqlite")
    tab = next(b for b in st.blocks("0000") if b.category == "Table")
    st.close()
    assert tab.decision == "arbiter" and tab.arbiter_status == "pending"  # waits for --models
    md = (out / "book.md").read_text(encoding="utf-8")
    assert "<table>" in md and ">9<" in md                # geometry is visible already in pass 1


def test_arbiter_crop_from_pdf(tmp_path):
    src = _pdf(tmp_path, [{"parts": [{"text": "Cell " * 40, "size": 9,
                                      "rects": [(28, 60, 570, 800)]}]}])
    doc = pymupdf.open(src)
    st_dir = tmp_path / "work"
    st_dir.mkdir()
    st = BookState(st_dir / "state.sqlite")
    entries = _lazy_entries(doc)
    st.add_pages(entries)
    files = {p.name: p.file for p in st.pages()}
    images = PdfPageImages(st_dir, files, src, st.pages())
    img = images.get("0000")
    assert abs(img.width - entries[0].width) <= 1 and abs(img.height - entries[0].height) <= 1
    st.close()


def test_resume_after_rendered_pending_keeps_pages(tmp_path):
    """CRITICAL: a page re-rendered for --models must not be lost on a rerun:
    a lazy entry has file="" in pages.json, while state already has "pages/N.png"."""
    from techbookocr.pipeline.runner import sync_pages
    from techbookocr.pipeline.textlayer import render_pending_pages

    src = _pdf(tmp_path, [{"image": True},   # vision page: re-rendered on --models
                          {"parts": [{"text": "Body " * 40, "size": 11,
                                      "rects": [(28, 60, 570, 700)]}]}])
    doc = pymupdf.open(src)
    st_dir = tmp_path / "work"
    st_dir.mkdir()
    st = BookState(st_dir / "state.sqlite")
    entries = _lazy_entries(doc)
    st.add_pages(entries)
    st.set_layout("0001", [], status="done")
    render_pending_pages(st, src, st_dir, lambda m: None)
    assert st.page("0000").file.endswith(".png")
    # rerun: the same lazy entries, sync must not delete the re-rendered page
    dropped = sync_pages(st, entries)
    assert dropped == []
    assert st.page("0000").layout_status == "pending"     # work is not reset
    st.close()


def test_extract_stats_merged_on_resume(tmp_path):
    """A second run_extract call (resume) supplements extract:stats instead of overwriting."""
    from techbookocr.pipeline.textlayer import run_extract

    src = _pdf(tmp_path, [{"parts": [{"text": "Body " * 40, "size": 11,
                                      "rects": [(28, 60, 570, 700)]}]},
                          {"image": True}])
    doc = pymupdf.open(src)
    st_dir = tmp_path / "work"
    st_dir.mkdir()
    st = BookState(st_dir / "state.sqlite")
    st.add_pages(_lazy_entries(doc))
    run_extract(st, src, st_dir, tmp_path / "out", CFG.pipeline)
    first = json.loads(st.get_meta("extract:stats"))
    assert first["layer_pages"] == 1 and first["vision_pages"] == 1
    # rerun: 0001 is still pending, the statistics must keep layer_pages
    run_extract(st, src, st_dir, tmp_path / "out", CFG.pipeline)
    merged = json.loads(st.get_meta("extract:stats"))
    assert merged["layer_pages"] == 1
    st.close()
