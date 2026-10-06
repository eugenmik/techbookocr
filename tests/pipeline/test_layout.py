import pytest
from PIL import Image

from techbookocr.models.errors import TransportError
from techbookocr.models.types import Block, PageResult
from techbookocr.pipeline.layout import layout_blocks, run_layout
from techbookocr.pipeline.state import PageEntry
from techbookocr.pipeline.transport import StageAborted, TransportGuard
from tests.pipeline.fakes import NO_SLEEP, FakePageOCR, new_state

PAGE = PageResult(markdown="", raw='[{"bbox": [1, 2, 3, 4]}]', seconds=1.5, blocks=[
    Block("Text", "Абзац", (100, 100, 900, 200)), Block("Picture", "", (100, 300, 500, 600)),
    Block("Table", "<table><tr><td>1</td></tr></table>", (100, 700, 900, 1200)),
    Block("Page-footer", "12", (450, 1300, 550, 1350)), Block("Text", "без рамки", None)])


def _guard():
    return TransportGuard(retries=1, max_consecutive=3, sleep=NO_SLEEP)


def test_layout_stores_blocks_and_figures(tmp_path):
    st = new_state(tmp_path)
    ocr = FakePageOCR([PAGE])
    assert run_layout(st, ocr, tmp_path / "work", tmp_path, 8, _guard()) == 2
    blocks = st.blocks("0001")
    assert [b.category for b in blocks] == ["Text", "Picture", "Table", "Page-footer"]  # block without a box is dropped
    assert blocks[1].image == "images/p0001_fig1.webp"
    with Image.open(tmp_path / "images" / "p0001_fig1.webp") as im:
        assert im.size == (416, 316)  # box 400x300 plus 8 px padding on every side
    assert st.page("0001").layout_status == "done" and st.page("0001").layout_seconds == 1.5
    assert st.pending("layout") == 0 and ocr.calls == 2
    assert run_layout(st, ocr, tmp_path / "work", tmp_path, 8, _guard()) == 0 and ocr.calls == 2  # resume
    st.close()


def test_layout_failure_becomes_page_block(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    bad = PageResult(markdown="", raw="ab" * 400, error="looping", blocks=[Block("Text", "abab", None)])
    run_layout(st, FakePageOCR([bad]), tmp_path / "work", tmp_path, 8, _guard())
    p, blocks = st.page("0001"), st.blocks("0001")
    assert p.layout_status == "failed" and p.layout_error == "looping"
    assert [(b.category, b.kind, b.bbox, b.drafts_status) for b in blocks] == [
        ("Page", "page", (0, 0, 1000, 1400), "pending")]
    st.close()


def test_truncated_page_keeps_blocks_and_blank_page_skipped(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    st.add_pages([PageEntry(name="0002", idx=1, scan=1, side="", file="pages/missing.png", width=10, height=10,
                            blank=True)])
    ocr = FakePageOCR([PageResult(markdown="", blocks=PAGE.blocks[:1], error="truncated")])
    run_layout(st, ocr, tmp_path / "work", tmp_path, 8, _guard())
    assert st.page("0001").layout_status == "done" and st.page("0001").layout_error == "truncated"
    assert st.page("0002").layout_status == "done" and st.page("0002").layout_error == "blank"
    assert ocr.calls == 1 and st.blocks("0002") == []
    st.close()


def test_empty_page_is_done():
    # Blank page with empty layout → done with no blocks
    status, blocks = layout_blocks(PageResult(markdown=""), (10, 10), is_blank=True)
    assert status == "done" and blocks == []
    # Non-blank page with empty layout → failed with Page block
    status, blocks = layout_blocks(PageResult(markdown=""), (10, 10), is_blank=False)
    assert status == "failed" and len(blocks) == 1 and blocks[0].category == "Page"


def test_transport_failure_marks_page_and_aborts_on_streak(tmp_path):
    st = new_state(tmp_path, names=("0001", "0002", "0003", "0004"))
    ocr = FakePageOCR([TransportError("down")])
    with pytest.raises(StageAborted) as e:
        run_layout(st, ocr, tmp_path / "work", tmp_path, 8, _guard())
    assert e.value.items == ["0001", "0002", "0003"]
    assert ocr.calls == 6  # 3 pages x (attempt + retry)
    p = st.page("0001")
    assert p.layout_status == "pending" and p.layout_error.startswith("transport:")
    assert st.page("0004").layout_status == "pending" and st.blocks() == []
    st.close()


def test_invalid_picture_bbox_keeps_page_done(tmp_path):
    """Out-of-bounds, inverted, zero-area Picture boxes → stage completes, page done."""
    st = new_state(tmp_path, names=("0001",))
    # Picture with out-of-bounds bbox, zero-area bbox, and valid bbox
    bad_page = PageResult(markdown="", raw="", seconds=1.0, blocks=[
        Block("Picture", "", (2000, 2000, 3000, 3000)),  # out-of-bounds
        Block("Picture", "", (100, 100, 100, 100)),      # zero-area
        Block("Text", "привет", (100, 100, 900, 200)),
        Block("Picture", "", (100, 300, 500, 600)),      # valid
    ])
    run_layout(st, FakePageOCR([bad_page]), tmp_path / "work", tmp_path, 8, _guard())
    p = st.page("0001")
    assert p.layout_status == "done"
    # Layout error should have bad_bbox count for 2 invalid Picture blocks
    assert p.layout_error == "bad_bbox:2"
    blocks = st.blocks("0001")
    # Invalid Picture blocks should be dropped; valid Picture and Text blocks kept
    assert len(blocks) == 2
    assert blocks[0].category == "Text"
    assert blocks[1].category == "Picture"
    st.close()


def test_figure_images_follow_filtered_blocks(tmp_path):
    """A broken Picture box before valid blocks: crops do not shift, each figure has its own file."""
    st = new_state(tmp_path, names=("0001",))
    page = PageResult(markdown="", blocks=[
        Block("Picture", "", (5000, 5000, 6000, 6000)),   # outside the page: dropped
        Block("Picture", "", (100, 300, 500, 600)),
        Block("Text", "текст", (100, 100, 900, 200)),
        Block("Picture", "", (100, 700, 500, 1100)),
    ])
    run_layout(st, FakePageOCR([page]), tmp_path / "work", tmp_path, 8, _guard())
    blocks = st.blocks("0001")
    assert [b.category for b in blocks] == ["Picture", "Text", "Picture"]
    assert blocks[1].image is None
    assert blocks[0].image and blocks[2].image and blocks[0].image != blocks[2].image
    with Image.open(tmp_path / blocks[0].image) as a, Image.open(tmp_path / blocks[2].image) as b:
        assert a.size == (416, 316) and b.size == (416, 416)  # each figure has its own crop
    st.close()


def test_success_resets_streak_no_abort(tmp_path):
    """fail, success, fail → no abort (streak reset after success)."""
    st = new_state(tmp_path, names=("0001", "0002", "0003"))
    # TransportError on page 0001 (retry succeeds with PAGE)
    # Success with PAGE on page 0002 (resets streak)
    # TransportError on page 0003 (retry succeeds with PAGE)
    # No abort because streak was reset by page 0002 success
    ocr = FakePageOCR([TransportError("down"), PAGE, PAGE])
    run_layout(st, ocr, tmp_path / "work", tmp_path, 8, _guard())
    assert st.page("0001").layout_status == "done"  # retry succeeds
    assert st.page("0002").layout_status == "done"  # direct success, resets streak
    assert st.page("0003").layout_status == "done"  # retry succeeds (streak was reset)
    st.close()
