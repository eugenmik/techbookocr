import json

import pytest

from techbookocr.config import Config, ConfigError, ModelSpec, PipelineConfig
from techbookocr.pipeline.state import BookState
from techbookocr.eval.cascade import cascade_report, evaluate, replay, run_golden, split_pages
from techbookocr.models.types import Block, BlockResult, PageResult
from tests.pipeline.fakes import TABLE_A, TABLE_B, TEXT, FakeVLM, Servers, fake_adapters, fake_deps, page_png

KEYS = ("dots_mocr", "hunyuan", "chandra2", "qwen9b_arbiter", "remote_arbiter")
CFG = Config(models={k: ModelSpec(key=k, adapter=k, image="img", model=k) for k in KEYS}, pipeline=PipelineConfig())
GOLD_TABLE = '<table><tr><td><img src="x"></td><td>15—25</td></tr></table>'
# draft A differs from B by one comma: CER ~ 0.03, numbers match
LAYOUT = PageResult(markdown="", seconds=1.0, blocks=[
    Block("Text", TEXT.replace(".", ","), (100, 100, 900, 120)), Block("Table", TABLE_A, (100, 220, 900, 400))])


def _golden(tmp_path):
    g = tmp_path / "golden"
    g.mkdir()
    (g / "manifest.toml").write_text('[[page]]\nid="p1"\nbook="b"\nscan=1\ncategories=["text"]\n'
                                     '[[page]]\nid="p2"\nbook="b"\nscan=2\ncategories=["table"]\n', encoding="utf-8")
    for pid in ("p1", "p2"):
        page_png(g / f"{pid}.png")
    (g / "p1.md").write_text(TEXT + "\n", encoding="utf-8")
    (g / "p2.md").write_text(TEXT + "\n\n" + GOLD_TABLE + "\n", encoding="utf-8")
    # sketch in the p2 table cell, where the detector stub will find it
    (g / "p2.figures.json").write_text(json.dumps({"figures": [[120, 240, 220, 340]], "in_table": [0]}))
    return g


def test_split_pages():
    md = "<!-- page: 1 scan: p1 -->\n\nА <!-- page: 2 scan: p2 --> б\n\n<!-- page: ? scan: p3 -->\n"
    assert split_pages(md) == {"p1": "\n\nА ", "p2": " б\n\n", "p3": "\n"}


def test_sweep_replay_and_seed(tmp_path):
    g = _golden(tmp_path)
    base = tmp_path / "cascade" / "cascade-qwen9b_arbiter"
    run_golden(CFG, g, base, arbiter="qwen9b_arbiter", sweep=True,
               **fake_deps(Servers(), fake_adapters(layout=LAYOUT)))
    assert set(split_pages((base / "book.md").read_text(encoding="utf-8"))) == {"p1", "p2"}
    strict = evaluate(base, g, 0.01, 0.15)
    loose = evaluate(base, g, 0.05, 0.15)
    assert strict["arbitration"] == 1.0 and loose["arbitration"] == 0.5  # at 0.05 the text is accepted without the arbiter
    assert strict["avg"]["cer"] < loose["avg"]["cer"]
    assert strict["fig"] == [0, 0, 0, 1, 1]  # sketch in the cell found
    servers = Servers()
    run_golden(CFG, g, tmp_path / "cascade" / "cascade-remote_arbiter", arbiter="remote_arbiter", sweep=True,
               seed=base, **fake_deps(servers, fake_adapters(layout=LAYOUT)))
    assert servers.started == ["remote_arbiter"]  # layout and drafts taken from the seed


def test_replay_uses_halluc_abs_chars(tmp_path):
    g = _golden(tmp_path)
    base = tmp_path / "cascade" / "cascade-qwen9b_arbiter"
    # the arbiter appends 2 characters to the text: within tolerance at abs_chars=3, outside it at abs_chars=1
    arb = FakeVLM(lambda prompt: BlockResult(
        (TABLE_B if "one table block" in prompt else TEXT.replace("углерод", "углеродаб")) + "\nFIXES: []", seconds=1.0))
    run_golden(CFG, g, base, arbiter="qwen9b_arbiter", sweep=True,
               **fake_deps(Servers(), fake_adapters(layout=LAYOUT, arbiter=arb)))
    strict = evaluate(base, g, 0.01, 0.0, halluc_abs_chars=1)
    loose = evaluate(base, g, 0.01, 0.0, halluc_abs_chars=3)
    assert strict["rejected"] > loose["rejected"]


def test_cascade_report(tmp_path):
    g = _golden(tmp_path)
    run_golden(CFG, g, tmp_path / "cascade" / "cascade-qwen9b_arbiter", arbiter="qwen9b_arbiter", sweep=True,
               **fake_deps(Servers(), fake_adapters(layout=LAYOUT)))
    single = tmp_path / "runs" / "single"
    single.mkdir(parents=True)
    for pid in ("p1", "p2"):
        (single / f"{pid}.md").write_text(TEXT + "\n", encoding="utf-8")
        (single / f"{pid}.json").write_text(json.dumps({"seconds": 2.0, "error": None, "blocks": []}))
    rep = cascade_report(g, tmp_path / "runs", tmp_path / "cascade", 0.01, 0.15, [0.01, 0.05], [0.15], [1, 3])
    assert "| cascade-qwen9b_arbiter |" in rep and "| single |" in rep
    assert "## Threshold sweep: cascade-qwen9b_arbiter" in rep and "| 0.05 | 0.15 | 3 |" in rep
    assert "## By category (cascade)" in rep


def test_replay_reproduces_run(tmp_path):
    import shutil

    from techbookocr.pipeline.runner import finish_book

    g = _golden(tmp_path)
    base = tmp_path / "cascade" / "cascade-qwen9b_arbiter"
    # text: a fix with an accepted was/now; table: a broken FIXES line -> parse note
    arb = FakeVLM(lambda prompt: BlockResult(
        TABLE_B + "\nFIXES: [oops" if "one table block" in prompt
        else TEXT.replace("Чугун", "Чугуна") + '\nFIXES: [{"was": "Чугун", "now": "Чугуна"}]', seconds=1.0))
    run_golden(CFG, g, base, arbiter="qwen9b_arbiter", **fake_deps(Servers(), fake_adapters(layout=LAYOUT, arbiter=arb)))
    cols = ("final", "final_source", "arbiter_status", "arbiter_note", "fixes", "decision", "cer_ab", "arbiter_cer")
    with BookState(base / "work" / "state.sqlite") as st:
        orig = [tuple(getattr(b, c) for c in cols) for b in st.blocks()]
    assert any(o[3] == "fixes unparsable" for o in orig) and any(o[4] for o in orig)
    copy = tmp_path / "copy"
    (copy / "work").mkdir(parents=True)
    shutil.copy(base / "work" / "state.sqlite", copy / "work" / "state.sqlite")
    p = CFG.pipeline
    with BookState(copy / "work" / "state.sqlite") as st:
        replay(st, p.tau_text, p.tau_halluc, "cascade", p.halluc_abs_chars, "ru")
        again = [tuple(getattr(b, c) for c in cols) for b in st.blocks()]
        finish_book(st, copy, book_name="golden", source=str(g), lang="ru", mode="cascade", models={}, speller=None)
    assert again == orig
    assert (copy / "book.md").read_text(encoding="utf-8") == (base / "book.md").read_text(encoding="utf-8")


def test_variant_guard_and_incomplete(tmp_path):
    g = _golden(tmp_path)
    base = tmp_path / "cascade" / "cascade-qwen9b_arbiter"
    run_golden(CFG, g, base, arbiter="qwen9b_arbiter", sweep=True, **fake_deps(Servers(), fake_adapters(layout=LAYOUT)))
    with pytest.raises(ConfigError):
        run_golden(CFG, g, base, arbiter="qwen9b_arbiter", sweep=False,
                   **fake_deps(Servers(), fake_adapters(layout=LAYOUT)))
    with pytest.raises(ConfigError):
        run_golden(CFG, g, base, arbiter="qwen9b_arbiter", sweep=True, mode="fast",
                   **fake_deps(Servers(), fake_adapters(layout=LAYOUT)))
    # unfinished variant: an incomplete stage and a cleared mark
    cut = tmp_path / "cascade2"
    cut.mkdir()
    import shutil
    shutil.copytree(base, cut / "cascade-broken")
    with BookState(cut / "cascade-broken" / "work" / "state.sqlite") as st:
        st.reset_stage("arbiter")
    rep = cascade_report(g, tmp_path / "runs", cut, 0.01, 0.15, [0.01], [0.15])
    assert "## Incomplete variants" in rep and "- cascade-broken:" in rep
    assert "| cascade-broken |" not in rep


def test_seed_is_atomic_and_report_cells(tmp_path):
    g = _golden(tmp_path)
    base = tmp_path / "cascade" / "cascade-qwen9b_arbiter"
    run_golden(CFG, g, base, arbiter="qwen9b_arbiter", sweep=True, **fake_deps(Servers(), fake_adapters(layout=LAYOUT)))
    out = tmp_path / "cascade" / "cascade-remote_arbiter"
    run_golden(CFG, g, out, arbiter="remote_arbiter", sweep=True, seed=base,
               **fake_deps(Servers(), fake_adapters(layout=LAYOUT)))
    assert not list((tmp_path / "cascade").glob(".*seed-tmp"))
    # the regular variant prints its thresholds; without a golden cell split, figure cells show "—"
    (g / "p2.figures.json").unlink()
    plain = tmp_path / "cascade" / "cascade-plain"
    run_golden(CFG, g, plain, arbiter="remote_arbiter", seed=base, **fake_deps(Servers(), fake_adapters(layout=LAYOUT)))
    rep = cascade_report(g, tmp_path / "none", tmp_path / "cascade", 0.01, 0.15, [0.01], [0.15])
    row = next(ln for ln in rep.splitlines() if ln.startswith("| cascade-plain |"))
    assert "0.01 / 0.15 / 3" in row and "| — | — |" in row
