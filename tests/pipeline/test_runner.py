import json

import pytest

from techbookocr.config import Config, ModelSpec, PipelineConfig
from techbookocr.models.errors import TransportError
from techbookocr.models.types import BlockResult
from techbookocr.pipeline.control import RunStopped
from techbookocr.pipeline.runner import RunOptions, run_book, run_pages
from techbookocr.pipeline.state import BookState, PageEntry
from techbookocr.pipeline.transport import StageAborted
from tests.pipeline.fakes import FakeVLM, Servers, fake_adapters, fake_deps, page_png

KEYS = ("dots_mocr", "hunyuan", "chandra2", "qwen9b_arbiter")
MODELS = {k: ModelSpec(key=k, adapter=k, image="img", model=k) for k in KEYS}
CFG = Config(models=MODELS, pipeline=PipelineConfig())


def _run(tmp_path, servers, adapters, mode="cascade", redo=None, cfg=CFG):
    entries = []
    for i, name in enumerate(("0001", "0002")):
        page_png(tmp_path / "out" / "work" / "pages" / f"{name}.png")
        entries.append(PageEntry(name=name, idx=i, scan=i, side="", file=f"pages/{name}.png", width=1000, height=1400))
    return run_pages(entries, tmp_path / "out", cfg, RunOptions(mode=mode, redo=redo), book_name="Книга",
                     source="book.djvu", **fake_deps(servers, adapters))


def test_full_cascade_and_resume(tmp_path):
    servers = Servers()
    out = _run(tmp_path, servers, fake_adapters())
    assert servers.started == ["dots_mocr", "hunyuan", "chandra2", "qwen9b_arbiter"]  # one model per stage
    md = (out / "book.md").read_text(encoding="utf-8")
    assert "<!-- page: ? scan: 0001 -->" in md and "<!-- page: ? scan: 0002 -->" in md
    assert md.count('<img src="images/p0001_tab1_cell1.webp">') == 1 and "15—25" in md
    assert "Чугун марки СЧ20 содержит углерод." in md and "$$\nx^2\n$$" in md and "\n\n12\n\n" not in md
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["mode"] == "cascade" and meta["pages"] == 2 and meta["lang"] == ["ru"]
    assert "Arbitrated share" in (out / "quality.md").read_text(encoding="utf-8")
    assert (out / "work" / "logs" / "run.log").exists()
    again = Servers()
    _run(tmp_path, again, fake_adapters())
    assert again.started == []  # all done: no models are started


def test_redo_arbiter_and_fast_mode(tmp_path):
    _run(tmp_path, Servers(), fake_adapters())
    servers = Servers()
    _run(tmp_path, servers, fake_adapters(), redo="arbiter")
    assert servers.started == ["qwen9b_arbiter"]
    servers = Servers()
    _run(tmp_path, servers, fake_adapters(), mode="fast")
    assert servers.started == ["qwen9b_arbiter"]  # the mode change reset drafts; there are no B drafts in fast
    st = BookState(tmp_path / "out" / "work" / "state.sqlite")
    blocks = [b for b in st.blocks("0001") if b.kind]
    assert {b.drafts_status for b in blocks} == {"skipped"}
    assert [b.decision for b in blocks] == ["accept", "arbiter", "accept"]
    st.close()


def test_transport_abort_restarts_server_then_resumes(tmp_path):
    cfg = Config(models=MODELS, pipeline=PipelineConfig(transport_retries=0, max_consecutive_failures=2))
    dead = FakeVLM(lambda prompt: TransportError("connection refused"))
    servers = Servers()
    with pytest.raises(StageAborted):
        _run(tmp_path, servers, fake_adapters(arbiter=dead), cfg=cfg)
    assert servers.started.count("qwen9b_arbiter") == 2 and len(dead.calls) == 3  # one restart; on the second pass the first series element is deferred
    st = BookState(tmp_path / "out" / "work" / "state.sqlite")
    assert st.pending("arbiter") == 2 and all(b.final is None for b in st.blocks() if b.decision == "arbiter")
    assert st.pending("drafts") == 0  # finished drafts are not lost
    st.close()
    assert not (tmp_path / "out" / "book.md").exists()
    servers = Servers()
    _run(tmp_path, servers, fake_adapters(), cfg=cfg)
    assert servers.started == ["qwen9b_arbiter"] and (tmp_path / "out" / "book.md").exists()


def test_run_book_from_pdf(tmp_path):
    import fitz

    pdf = tmp_path / "Автор_Книга_1980.pdf"
    doc = fitz.open()
    for _ in range(2):
        doc.new_page(width=420, height=595).insert_text((72, 72), "Cast iron")
    doc.save(pdf)
    out = run_book(pdf, tmp_path / "out", CFG, RunOptions(keep_work=True),
                   **fake_deps(Servers(), fake_adapters()))
    assert out == tmp_path / "out" / "Автор_Книга_1980"
    st = BookState(out / "work" / "state.sqlite")
    assert [(p.name, p.idx) for p in st.pages()] == [("0000", 0), ("0001", 2)]
    st.close()
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["author"] == "Автор" and meta["year"] == 1980 and meta["title"] == "Книга"


def test_run_book_removes_work_by_default(tmp_path):
    """A built book does not keep work/: book.md, <name>.md, images/, meta.json, quality.md remain.
    keep_work=True keeps work/ (debugging state.sqlite)."""
    import fitz

    for name, opts in (("a.pdf", RunOptions()), ("b.pdf", RunOptions(keep_work=True))):
        doc = fitz.open()
        doc.new_page(width=420, height=595).insert_text((72, 72), "Cast iron")
        doc.save(tmp_path / name)
        doc.close()
    out_a = run_book(tmp_path / "a.pdf", tmp_path / "out", CFG, RunOptions(),
                     **fake_deps(Servers(), fake_adapters()))
    out_b = run_book(tmp_path / "b.pdf", tmp_path / "out", CFG, RunOptions(keep_work=True),
                     **fake_deps(Servers(), fake_adapters()))
    assert not (out_a / "work").exists()
    assert (out_a / "book.md").exists() and (out_a / "meta.json").exists()
    assert (out_a / "quality.md").exists() and (out_a / "a.md").exists()
    assert (out_b / "work" / "state.sqlite").exists()


def test_sketches_device_reaches_detector(tmp_path):
    """[pipeline] sketches_device reaches detector_factory as the device argument."""
    got = {}
    deps = fake_deps(Servers(), fake_adapters())
    real_factory = deps["detector_factory"]

    def rec(**kw):
        got.update(kw)
        return real_factory()

    deps["detector_factory"] = rec
    cfg = Config(models=MODELS, pipeline=PipelineConfig(sketches_device="gpu"))
    entries = []
    for i, name in enumerate(("0001", "0002")):
        page_png(tmp_path / "out" / "work" / "pages" / f"{name}.png")
        entries.append(PageEntry(name=name, idx=i, scan=i, side="", file=f"pages/{name}.png",
                                 width=1000, height=1400))
    run_pages(entries, tmp_path / "out", cfg, RunOptions(), book_name="Книга", source="b.djvu", **deps)
    assert got["device"] == "gpu"


def test_config_thresholds_reach_stages(tmp_path):
    """tau_text from [pipeline] reaches consensus: with tau_text=0 text A!=B goes to the arbiter no sooner than needed,
    and with large tau_halluc/halluc_abs_chars the arbiter reply is not rejected."""
    cfg = Config(models=MODELS, pipeline=PipelineConfig(halluc_abs_chars=1000, tau_halluc=1.0))
    out = _run(tmp_path, Servers(), fake_adapters(), cfg=cfg)
    st = BookState(out / "work" / "state.sqlite")
    assert not [b for b in st.blocks() if b.arbiter_status == "rejected"]
    st.close()


def test_run_pages_validates_options(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        _run(tmp_path, Servers(), fake_adapters(), mode="slow")
    with pytest.raises(ValueError, match="redo"):
        _run(tmp_path, Servers(), fake_adapters(), redo="x")
    bad = Config(models={}, pipeline=PipelineConfig())
    with pytest.raises(ValueError, match="models not in config"):
        _run(tmp_path, Servers(), fake_adapters(), cfg=bad)


def _entries(tmp_path, specs):
    out = []
    for name, idx, scan, side, w, h in specs:
        page_png(tmp_path / "out" / "work" / "pages" / f"{name}.png")
        out.append(PageEntry(name=name, idx=idx, scan=scan, side=side, file=f"pages/{name}.png", width=w, height=h))
    return out


def _go(tmp_path, entries, servers=None, adapters=None, cfg=CFG, opts=None, renders=None):
    return run_pages(entries, tmp_path / "out", cfg, opts or RunOptions(), book_name="Книга", source="b.djvu",
                     renders=renders, **fake_deps(servers or Servers(), adapters or fake_adapters()))


def test_render_change_resets_layout_for_changed_pages(tmp_path):
    _go(tmp_path, _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400), ("0002", 1, 1, "", 1000, 1400)]))
    servers = Servers()
    _go(tmp_path, _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400), ("0002", 1, 1, "", 2000, 2800)]), servers)
    assert servers.started[0] == "dots_mocr"  # layout repeated only because of the changed page
    st = BookState(tmp_path / "out" / "work" / "state.sqlite")
    assert st.page("0002").width == 2000 and st.page("0001").width == 1000
    st.close()
    # only the render hash changed
    _go(tmp_path, _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400), ("0002", 1, 1, "", 2000, 2800)]),
        renders={"0001": "a", "0002": "a"})
    servers = Servers()
    _go(tmp_path, _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400), ("0002", 1, 1, "", 2000, 2800)]), servers,
        renders={"0001": "b", "0002": "a"})
    assert servers.started and servers.started[0] == "dots_mocr"


def test_split_spreads_change_removes_old_pages(tmp_path):
    _go(tmp_path, _entries(tmp_path, [("0000L", 0, 0, "L", 1000, 1400), ("0000R", 1, 0, "R", 1000, 1400)]))
    out = _go(tmp_path, _entries(tmp_path, [("0000", 0, 0, "", 1000, 1400)]))  # no IntegrityError
    st = BookState(out / "work" / "state.sqlite")
    assert [p.name for p in st.pages()] == ["0000"]
    assert {b.page for b in st.blocks()} == {"0000"}
    st.close()
    assert "scan: 0000" in (out / "book.md").read_text(encoding="utf-8")


def _table_layout(html):
    from techbookocr.models.types import Block, PageResult

    return PageResult(markdown="", seconds=1.0, blocks=[Block("Table", html, (100, 220, 900, 400))])


class _KillableArbiter:
    """Arbiter server: after a request with POISON it "dies" and all following requests fail too (until restart)."""

    vision = True

    def __init__(self):
        self.dead, self.closed = False, False

    def ask(self, image, prompt, *, max_tokens=None):
        if "POISON" in prompt:
            self.dead = True
        if self.dead:
            raise TransportError("server died")
        return BlockResult("<table><tr><td>ok</td></tr></table>\nFIXES: []", seconds=1.0)

    def close(self):
        self.closed = True


def test_real_poison_block_is_failed_while_others_succeed(tmp_path):
    from tests.pipeline.fakes import FakePageOCR

    cfg = Config(models=MODELS, pipeline=PipelineConfig(transport_retries=0, max_consecutive_failures=2))
    layouts = [_table_layout(f"<table><tr><td>{t}</td></tr></table>") for t in ("a", "POISON", "c", "d")]
    base = fake_adapters()

    def adapters(spec, url):
        if spec.key == "dots_mocr":
            return FakePageOCR(layouts)
        if spec.key == "qwen9b_arbiter":
            return _KillableArbiter()
        return base(spec, url)

    ents = _entries(tmp_path, [(f"000{i}", i, i, "", 1000, 1400) for i in range(1, 5)])
    out = _go(tmp_path, ents, adapters=adapters, cfg=cfg)
    st = BookState(out / "work" / "state.sqlite")
    failed = [b for b in st.blocks() if b.arbiter_status == "failed"]
    assert len(failed) == 1 and "POISON" in failed[0].text_a and "poison" in failed[0].arbiter_error
    assert [b.arbiter_status for b in st.blocks() if b.page != failed[0].page] == ["done"] * 3
    assert st.pending("arbiter") == 0 and (out / "book.md").exists()
    st.close()


def test_persistent_outage_never_marks_poison_and_never_assembles(tmp_path):
    cfg = Config(models=MODELS, pipeline=PipelineConfig(transport_retries=0, max_consecutive_failures=2))
    ents = _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400), ("0002", 1, 1, "", 1000, 1400)])
    for _ in range(3):
        dead = FakeVLM(lambda prompt: TransportError("503"))
        with pytest.raises(StageAborted):
            _go(tmp_path, ents, adapters=fake_adapters(arbiter=dead), cfg=cfg)
        st = BookState(tmp_path / "out" / "work" / "state.sqlite")
        assert st.pending("arbiter") == 2
        assert not [b for b in st.blocks() if b.arbiter_status == "failed"]
        st.close()
        assert not (tmp_path / "out" / "book.md").exists()


def test_tail_transport_failure_leaves_item_pending_and_aborts(tmp_path):
    """A tail failure (the series did not fill up) does not mark the item failed and does not let the book be assembled."""
    cfg = Config(models=MODELS, pipeline=PipelineConfig(transport_retries=0, max_consecutive_failures=3))
    calls = []

    def reply(prompt):
        calls.append(1)
        return TransportError("blip") if len(calls) >= 2 else BlockResult("<table></table>\nFIXES: []", seconds=1.0)

    ents = _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400), ("0002", 1, 1, "", 1000, 1400)])
    with pytest.raises(StageAborted):
        _go(tmp_path, ents, adapters=fake_adapters(arbiter=FakeVLM(reply)), cfg=cfg)
    st = BookState(tmp_path / "out" / "work" / "state.sqlite")
    assert st.pending("arbiter") == 1 and not [b for b in st.blocks() if b.arbiter_status == "failed"]
    st.close()
    assert not (tmp_path / "out" / "book.md").exists()


def test_fresh_fast_run_skips_drafts(tmp_path):
    servers = Servers()
    out = _go(tmp_path, _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400)]), servers,
              opts=RunOptions(mode="fast"))
    assert servers.started == ["dots_mocr", "qwen9b_arbiter"]
    st = BookState(out / "work" / "state.sqlite")
    assert {b.drafts_status for b in st.blocks() if b.kind} == {"skipped"}
    st.close()


def test_lang_change_resets_arbiter(tmp_path):
    ents = _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400)])
    _go(tmp_path, ents)
    servers = Servers()
    _go(tmp_path, ents, servers, opts=RunOptions(lang="en"))
    assert servers.started == ["qwen9b_arbiter"]


def test_empty_book_is_config_error(tmp_path):
    from techbookocr.config import ConfigError

    with pytest.raises(ConfigError, match="no pages"):
        _go(tmp_path, [])


def _poison_adapters(poison_pages, n_pages):
    from tests.pipeline.fakes import FakePageOCR

    layouts = [_table_layout(f"<table><tr><td>{'POISON' if i in poison_pages else 'ok'}{i}</td></tr></table>")
               for i in range(1, n_pages + 1)]
    base = fake_adapters()

    def adapters(spec, url):
        if spec.key == "dots_mocr":
            return FakePageOCR(layouts)
        if spec.key == "qwen9b_arbiter":
            return _KillableArbiter()
        return base(spec, url)

    return adapters


_POISON_CFG = Config(models=MODELS, pipeline=PipelineConfig(transport_retries=0, max_consecutive_failures=2))


def _poisoned(out):
    st = BookState(out / "work" / "state.sqlite")
    r = [b for b in st.blocks() if b.arbiter_status == "failed" and "poison" in (b.arbiter_error or "")]
    pend = st.pending("arbiter")
    st.close()
    return r, pend


@pytest.mark.parametrize("poison_pages,n", [({4}, 4), ({1}, 1)])
def test_poison_as_last_or_only_pending_item(tmp_path, poison_pages, n):
    ents = _entries(tmp_path, [(f"000{i}", i, i, "", 1000, 1400) for i in range(1, n + 1)])
    out = None
    for _ in range(2):  # at most two launches
        try:
            out = _go(tmp_path, ents, adapters=_poison_adapters(poison_pages, n), cfg=_POISON_CFG)
            break
        except StageAborted:
            pass
    assert out is not None
    r, pend = _poisoned(out)
    assert len(r) == len(poison_pages) and pend == 0 and (out / "book.md").exists()


def test_two_poison_items_resolved_within_two_runs(tmp_path):
    ents = _entries(tmp_path, [(f"000{i}", i, i, "", 1000, 1400) for i in range(1, 5)])
    out = None
    for _ in range(2):
        try:
            out = _go(tmp_path, ents, adapters=_poison_adapters({2, 4}, 4), cfg=_POISON_CFG)
            break
        except StageAborted:
            pass
    assert out is not None
    r, pend = _poisoned(out)
    assert len(r) == 2 and pend == 0
    st = BookState(out / "work" / "state.sqlite")
    assert not [b for b in st.blocks() if b.arbiter_status == "deferred"]
    st.close()


def test_aborted_run_persists_no_deferred_status(tmp_path):
    ents = _entries(tmp_path, [(f"000{i}", i, i, "", 1000, 1400) for i in range(1, 5)])
    dead = FakeVLM(lambda prompt: TransportError("down"))
    for _ in range(2):
        with pytest.raises(StageAborted):
            _go(tmp_path, ents, adapters=fake_adapters(arbiter=dead), cfg=_POISON_CFG)
    st = BookState(tmp_path / "out" / "work" / "state.sqlite")
    assert "deferred" not in {b.arbiter_status for b in st.blocks()} and st.pending("arbiter") == 4
    st.close()


def test_legacy_deferred_status_is_restored_and_processed(tmp_path):
    ents = _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400), ("0002", 1, 1, "", 1000, 1400)])
    out = _go(tmp_path, ents)
    st = BookState(out / "work" / "state.sqlite")
    st.conn.execute("UPDATE blocks SET arbiter_status='deferred', final=NULL WHERE decision='arbiter'")
    st.conn.execute("UPDATE pages SET layout_status='deferred' WHERE name='0002'")
    st.conn.execute("DELETE FROM meta WHERE key LIKE 'done:%'")
    st.close()
    (out / "book.md").unlink()
    servers = Servers()
    out = _go(tmp_path, ents, servers)  # layout of page 0002 is repeated, the arbiter finishes the blocks
    assert "dots_mocr" in servers.started and "qwen9b_arbiter" in servers.started
    st = BookState(out / "work" / "state.sqlite")
    assert not [b for b in st.blocks() if b.arbiter_status == "deferred"] and st.page("0002").layout_status == "done"
    assert all(b.final is not None for b in st.blocks() if b.decision == "arbiter")
    st.close()
    assert (out / "book.md").exists()


def test_give_up_transport_marks_failed_and_assembles(tmp_path):
    ents = _entries(tmp_path, [("0001", 0, 0, "", 1000, 1400), ("0002", 1, 1, "", 1000, 1400)])
    dead = FakeVLM(lambda prompt: TransportError("503"))
    with pytest.raises(StageAborted):
        _go(tmp_path, ents, adapters=fake_adapters(arbiter=dead), cfg=_POISON_CFG)
    out = _go(tmp_path, ents, adapters=fake_adapters(arbiter=dead), cfg=_POISON_CFG,
              opts=RunOptions(give_up_transport=True))
    st = BookState(out / "work" / "state.sqlite")
    assert st.pending("arbiter") == 0 and {b.arbiter_status for b in st.blocks() if b.decision == "arbiter"} == {"failed"}
    st.close()
    assert (out / "book.md").exists()


class StopAfter:
    """Control stub: raises RunStopped on the (n+1)-th poll call; records stage names."""
    def __init__(self, n):
        self.n, self.calls, self.stages = n, 0, []
    def set_stage(self, stage):
        self.stages.append(stage)
    def poll(self):
        self.calls += 1
        if self.calls > self.n:
            raise RunStopped("queued")


def _named_entries(tmp_path, names):
    entries = []
    for i, name in enumerate(names):
        page_png(tmp_path / "out" / "work" / "pages" / f"{name}.png")
        entries.append(PageEntry(name=name, idx=i, scan=i, side="", file=f"pages/{name}.png",
                                 width=1000, height=1400))
    return entries


def test_control_stop_leaves_book_resumable(tmp_path):
    entries = _named_entries(tmp_path, ("0001", "0002", "0003"))
    ctl = StopAfter(2)  # 2 layout pages, stop on the 3rd
    with pytest.raises(RunStopped):
        run_pages(entries, tmp_path / "out", CFG, RunOptions(), book_name="Книга", source="b.djvu",
                  control=ctl, **fake_deps(Servers(), fake_adapters()))
    assert "layout" in ctl.stages
    st = BookState(tmp_path / "out" / "work" / "state.sqlite")
    assert st.pending("layout") == 1
    st.close()
    run_pages(entries, tmp_path / "out", CFG, RunOptions(), book_name="Книга", source="b.djvu",
              **fake_deps(Servers(), fake_adapters()))  # without control it runs to the end
    assert (tmp_path / "out" / "book.md").exists()
