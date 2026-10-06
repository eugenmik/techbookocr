import pytest

from techbookocr.config import PipelineConfig
from techbookocr.models.errors import TransportError
from techbookocr.models.types import Block, BlockResult
from techbookocr.pipeline.drafts import TABLE_MODEL_KINDS, TEXT_MODEL_KINDS, run_drafts
from techbookocr.pipeline.state import PAGE_CATEGORY
from techbookocr.pipeline.transport import StageAborted, TransportGuard
from tests.pipeline.fakes import NO_SLEEP, FakeBlockOCR, new_state

CFG = PipelineConfig()
BLOCKS = [Block("Section-header", "Глава", (100, 100, 900, 120)),  # one "line" 20 px high
          Block("Table", "<table></table>", (100, 220, 900, 400)),
          Block("Formula", "$$x$$", (100, 460, 900, 480)),
          Block("Picture", "", (100, 600, 500, 900))]


def _guard(**kw):
    return TransportGuard(sleep=NO_SLEEP, **kw)


def test_models_get_only_their_kinds(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    st.set_layout("0001", BLOCKS, status="done")
    ocr = FakeBlockOCR()
    assert run_drafts(st, ocr, tmp_path / "work", CFG, _guard(), TEXT_MODEL_KINDS) == 2
    assert [k for _, k in ocr.calls] == ["title", "formula"]
    # a 20 px line -> upscale x1.6 to 32 px; crop with padding 12: 824x44
    assert ocr.calls[0][0] == (round(824 * 1.6), round(44 * 1.6))
    head, table, formula, pic = st.blocks("0001")
    assert head.text_b == "B:title" and head.drafts_status == "done"
    assert table.drafts_status == "pending" and pic.drafts_status == "skipped"
    tab = FakeBlockOCR(lambda img, kind: BlockResult("<table><tr><td>1</td></tr></table>", seconds=2.0))
    run_drafts(st, tab, tmp_path / "work", CFG, _guard(), TABLE_MODEL_KINDS)
    table = st.blocks("0001")[1]
    assert table.text_b.startswith("<table>") and table.b_seconds == 2.0 and st.pending("drafts") == 0
    st.close()


def test_page_block_gets_whole_page(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    st.set_layout("0001", [Block(PAGE_CATEGORY, "", (0, 0, 1000, 1400))], status="failed", error="looping")
    ocr = FakeBlockOCR()
    run_drafts(st, ocr, tmp_path / "work", CFG, _guard(), TEXT_MODEL_KINDS)
    assert ocr.calls == [((1000, 1400), "page")]
    st.close()


def test_content_error_marks_failed_and_resume(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    st.set_layout("0001", BLOCKS, status="done")
    ocr = FakeBlockOCR(lambda img, kind: BlockResult("abab", error="looping"))
    run_drafts(st, ocr, tmp_path / "work", CFG, _guard(), TEXT_MODEL_KINDS)
    head = st.blocks("0001")[0]
    assert head.drafts_status == "failed" and head.b_error == "looping" and head.text_b == "abab"
    n = len(ocr.calls)
    assert run_drafts(st, ocr, tmp_path / "work", CFG, _guard(), TEXT_MODEL_KINDS) == 0 and len(ocr.calls) == n
    st.close()


def test_transport_streak_aborts(tmp_path):
    st = new_state(tmp_path, names=("0001", "0002"))
    for name in ("0001", "0002"):
        st.set_layout(name, BLOCKS, status="done")
    ocr = FakeBlockOCR(lambda img, kind: TransportError("down"))
    with pytest.raises(StageAborted) as e:
        run_drafts(st, ocr, tmp_path / "work", CFG, _guard(retries=1), TEXT_MODEL_KINDS)
    assert len(e.value.items) == 3 and len(ocr.calls) == 6
    assert st.pending("drafts", TEXT_MODEL_KINDS) == 4  # a transport failure does not mark failed: everything is pending
    assert not [b for b in st.blocks() if b.drafts_status == "failed"]
    st.close()


def test_mask_boxes_only_for_text_kinds_with_inner_table_or_picture():
    from techbookocr.pipeline.drafts import mask_boxes
    from techbookocr.pipeline.state import BlockRow
    text = BlockRow(id=1, page="p", ord=0, category="Text", kind="text", bbox=(400, 300, 3000, 2000))
    tab = BlockRow(id=2, page="p", ord=1, category="Table", kind="table", bbox=(1600, 1000, 3000, 1900))
    pic = BlockRow(id=3, page="p", ord=2, category="Picture", bbox=(100, 100, 500, 400))  # only the edge is inside
    sketch = BlockRow(id=4, page="p", ord=3, category="Picture", bbox=(1700, 1100, 1800, 1200), parent=2)
    assert mask_boxes(text, [text, tab, pic, sketch]) == ((1600, 1000, 3000, 1900),)
    assert mask_boxes(tab, [text, tab]) == ()
    formula = BlockRow(id=5, page="p", ord=4, category="Formula", kind="formula", bbox=(1500, 900, 3100, 2000))
    assert mask_boxes(formula, [tab, formula]) == ((1600, 1000, 3000, 1900),)


def test_failed_parse_stores_raw_answer_in_text_b(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    st.set_layout("0001", BLOCKS, status="done")
    ocr = FakeBlockOCR(lambda img, kind: BlockResult("", raw="<p>нет таблицы</p>", error="parse_error: no <table>"))
    run_drafts(st, ocr, tmp_path / "work", CFG, _guard(), TEXT_MODEL_KINDS)
    head = st.blocks("0001")[0]
    assert head.drafts_status == "failed" and head.text_b == "<p>нет таблицы</p>" and "no <table>" in head.b_error
    st.close()
