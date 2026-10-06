import pytest

from techbookocr.models.types import Block
from techbookocr.pipeline.state import STAGES, BookState, PageEntry

BLOCKS = [Block("Text", "Абзац", (10, 10, 900, 100)), Block("Table", "<table></table>", (10, 200, 900, 800)),
          Block("Picture", "", (10, 900, 500, 1300)), Block("Page-footer", "12", (400, 1350, 500, 1390))]


def _state(tmp_path, n=2):
    st = BookState(tmp_path / "work" / "state.sqlite")
    st.add_pages([PageEntry(name=f"000{i}", idx=i, scan=i, side="", file=f"pages/000{i}.png", width=1000, height=1400)
                  for i in range(n)])
    return st


def test_pages_idempotent_and_ordered(tmp_path):
    st = _state(tmp_path)
    st.add_pages([PageEntry(name="0001", idx=1, scan=1, side="", file="x", width=1, height=1),
                  PageEntry(name="0005", idx=5, scan=5, side="", file="pages/0005.png", width=10, height=20)])
    assert [p.name for p in st.pages()] == ["0000", "0001", "0005"]
    assert st.page("0001").file == "pages/0001.png"  # a known page is not overwritten
    assert st.pending("layout") == 3
    st.close()


def test_set_layout_statuses(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS, status="done", error="truncated", raw="{}", seconds=2.5,
                  images={2: "images/p0000_fig2.png"})
    blocks = st.blocks("0000")
    assert [(b.ord, b.category, b.kind) for b in blocks] == [
        (0, "Text", "text"), (1, "Table", "table"), (2, "Picture", None), (3, "Page-footer", None)]
    assert [b.drafts_status for b in blocks] == ["pending", "pending", "skipped", "skipped"]
    assert [b.sketches_status for b in blocks] == ["skipped", "pending", "skipped", "skipped"]
    assert blocks[2].image == "images/p0000_fig2.png" and blocks[0].bbox == (10, 10, 900, 100)
    p = st.page("0000")
    assert p.layout_status == "done" and p.layout_error == "truncated" and p.layout_seconds == 2.5
    assert st.pending("layout") == 1 and st.pending("drafts") == 2 and st.pending("drafts", {"table"}) == 1
    assert [b.ord for b in st.pending_blocks("drafts", {"text", "title"})] == [0]
    st.close()


def test_set_layout_is_atomic(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS[:1], status="done")
    with pytest.raises(ValueError):  # the second box is broken: an exception in the middle of an insert
        st.set_layout("0000", [Block("Text", "новый", (1, 1, 5, 5)), Block("Text", "битый", (1, 2, 3))],
                      status="done")
    assert [b.text_a for b in st.blocks("0000")] == ["Абзац"]  # old blocks are in place, no new ones
    st.close()


def test_reopen_resumes(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS, status="done")
    bid = st.blocks("0000")[0].id
    st.update_block(bid, text_b="Абзац", drafts_status="done", fixes=[{"was": "а", "now": "б"}])
    st.set_meta("lang", "ru")
    st.close()
    st = BookState(tmp_path / "work" / "state.sqlite")
    b = st.block(bid)
    assert b.text_b == "Абзац" and b.drafts_status == "done" and b.fixes == [{"was": "а", "now": "б"}]
    assert st.get_meta("lang") == "ru" and st.pending("layout") == 1
    st.close()


def test_update_block_whitelist(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS, status="done")
    with pytest.raises(ValueError, match="not updatable"):
        st.update_block(st.blocks()[0].id, category="Title")
    with pytest.raises(KeyError):
        st.update_block(99999, final="x")
    st.close()


def test_reset_stage_cascades(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS, status="done")
    text, table = st.blocks("0000")[:2]
    st.update_block(text.id, text_b="Абзац", drafts_status="done", decision="accept", consensus_status="done",
                    final="Абзац", final_source="a")
    st.update_block(table.id, text_b="<table/>", drafts_status="done", decision="arbiter", consensus_status="done",
                    arbiter_status="done", arbiter_text="<table/>", final="<table/>", final_source="arbiter")
    st.mark_done("postproc")
    st.mark_done("assemble")
    st.reset_stage("arbiter")
    t, tb = st.block(text.id), st.block(table.id)
    assert t.final == "Абзац" and t.arbiter_status == "skipped"
    assert tb.final is None and tb.arbiter_status == "pending" and tb.arbiter_text is None
    assert st.pending("postproc") == 1 and st.pending("assemble") == 1
    st.reset_stage("drafts")
    t = st.block(text.id)
    assert t.text_b is None and t.drafts_status == "pending" and t.decision is None and t.final is None
    assert t.consensus_status == "pending"
    st.close()


def test_reset_items_and_skip(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS, status="done")
    st.set_layout("0001", BLOCKS[:1], status="done")
    ids = [b.id for b in st.blocks() if b.kind == "text"]
    for i in ids:
        st.update_block(i, drafts_status="failed", b_error="transport: x")
    st.reset_items("drafts", ids[:1])
    assert st.block(ids[0]).drafts_status == "pending" and st.block(ids[1]).drafts_status == "failed"
    st.reset_items("layout", ["0001"])
    assert st.page("0001").layout_status == "pending" and st.blocks("0001") == []
    st.skip_pending("drafts")
    assert st.pending("drafts") == 0
    st.close()


def test_timings_and_unknown_stage(tmp_path):
    st = _state(tmp_path)
    st.add_seconds("layout", 1.5)
    st.add_seconds("layout", 2.0)
    st.add_seconds("arbiter", 3)
    assert st.timings() == {"layout": 3.5, "arbiter": 3.0}
    with pytest.raises(ValueError):
        st.pending("nope")
    with pytest.raises(ValueError):
        st.reset_stage("nope")
    assert STAGES[0] == "layout" and STAGES[-1] == "assemble"
    st.close()


def test_schema_version(tmp_path):
    # Create new DB - should have version 1
    st = _state(tmp_path)
    st.close()
    # Reopen same DB - should work fine
    st = BookState(tmp_path / "work" / "state.sqlite")
    st.close()
    # Manually change version to 2 and try to reopen
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "work" / "state.sqlite"))
    conn.execute("PRAGMA user_version=2")
    conn.close()
    with pytest.raises(ValueError, match=r"state.sqlite schema v2, expected v1"):
        BookState(tmp_path / "work" / "state.sqlite")


def test_reset_items_cascades_and_clears_done_flags(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS, status="done")
    text, table = st.blocks("0000")[:2]
    # Progress through stages
    st.update_block(text.id, text_b="Абзац", drafts_status="done", decision="accept", consensus_status="done",
                    final="Абзац", final_source="a")
    st.update_block(table.id, text_b="<table/>", drafts_status="done", decision="arbiter", consensus_status="done",
                    arbiter_status="done", arbiter_text="<table/>", final="<table/>", final_source="arbiter")
    st.mark_done("postproc")
    st.mark_done("assemble")
    # Now reset_items("drafts", [text.id]) should cascade to arbiter and clear postproc/assemble
    st.reset_items("drafts", [text.id])
    t, tb = st.block(text.id), st.block(table.id)
    # text block: all downstream stages cleared
    assert t.text_b is None and t.drafts_status == "pending" and t.decision is None
    assert t.consensus_status == "pending" and t.arbiter_status == "skipped" and t.final is None
    # table block: unchanged
    assert tb.text_b == "<table/>" and tb.drafts_status == "done" and tb.decision == "arbiter"
    # postproc/assemble flags cleared
    assert st.pending("postproc") == 1 and st.pending("assemble") == 1
    st.close()


def test_reset_items_drafts_clears_downstream(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS[:2], status="done")
    text, table = st.blocks("0000")
    st.update_block(text.id, text_b="text", drafts_status="done", decision="accept", consensus_status="done",
                    arbiter_status="done", arbiter_text="x", final="text", final_source="a")
    st.update_block(table.id, text_b="table", drafts_status="done", decision="arbiter", consensus_status="done",
                    arbiter_status="done", arbiter_text="y", final="table", final_source="arbiter")
    st.mark_done("postproc")
    st.mark_done("assemble")
    # reset_items("drafts", [table.id]) should reset only table's downstream
    st.reset_items("drafts", [table.id])
    t, tb = st.block(text.id), st.block(table.id)
    # text: unchanged
    assert t.text_b == "text" and t.final == "text" and t.arbiter_status == "done"
    # table: downstream cleared
    assert tb.text_b is None and tb.drafts_status == "pending" and tb.decision is None
    assert tb.final is None and tb.arbiter_status == "skipped" and tb.arbiter_text is None
    # postproc/assemble flags cleared
    assert st.get_meta("done:postproc") is None and st.get_meta("done:assemble") is None
    st.close()


def test_reset_assemble_preserves_postproc_flag(tmp_path):
    st = _state(tmp_path)
    st.set_layout("0000", BLOCKS[:1], status="done")
    st.mark_done("postproc")
    st.mark_done("assemble")
    # Resetting assemble should clear done:assemble but NOT done:postproc
    st.reset_stage("assemble")
    assert st.get_meta("done:postproc") == "1" and st.get_meta("done:assemble") is None
    st.close()


def test_set_layout_unknown_page_raises(tmp_path):
    st = _state(tmp_path)
    with pytest.raises(KeyError, match="unknown"):
        st.set_layout("unknown", BLOCKS, status="done")
    # Verify db is clean (transaction rolled back)
    st.close()
    st = BookState(tmp_path / "work" / "state.sqlite")
    assert st.blocks("0000") == []
    assert st.blocks("0001") == []
    st.close()
