import json

import pytest

from techbookocr.eval.figures import (figure_cells, figure_scores, iou, load_gold_figures, load_gold_split, match_boxes,
                                  pred_figures, split_figure_counts)
from techbookocr.eval.report import build_report


def test_iou_and_matching():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    s = figure_scores([(0, 0, 100, 100), (300, 300, 400, 400)], [(0, 0, 100, 90)])
    assert s["matched"] == 1 and s["n_pred"] == 2 and s["n_gold"] == 1
    assert s["precision"] == 0.5 and s["recall"] == 1.0
    assert 0.85 < s["mean_iou"] < 0.95


def test_one_to_one():
    s = figure_scores([(0, 0, 100, 100), (0, 0, 100, 95)], [(0, 0, 100, 100)])
    assert s["matched"] == 1 and s["precision"] == 0.5 and s["recall"] == 1.0


def test_threshold_miss():
    s = figure_scores([(0, 0, 10, 10)], [(5, 5, 100, 100)])
    assert s["matched"] == 0 and s["f1"] == 0.0


def test_edge_cases():
    assert figure_scores(None, [(0, 0, 1, 1)]) is None
    e = figure_scores([], [])
    assert e["precision"] == e["recall"] == e["f1"] == 1.0
    e = figure_scores([(0, 0, 5, 5)], [])
    assert e["precision"] == 0.0 and e["recall"] == 1.0


def test_pred_figures_and_load(tmp_path):
    assert pred_figures([]) is None
    blocks = [{"category": "Picture", "bbox": [1, 2, 30, 40]}, {"category": "Text", "bbox": [0, 0, 5, 5]},
              {"category": "Picture", "bbox": None}, {"category": "Picture", "bbox": [5, 5, 5, 9]}]
    assert pred_figures(blocks) == [(1, 2, 30, 40)]
    assert pred_figures([{"category": "Text", "bbox": [0, 0, 5, 5]}]) == []
    assert load_gold_figures(tmp_path, "x") is None
    (tmp_path / "x.figures.json").write_text(json.dumps({"figures": [[1, 2, 3, 4]]}))
    assert load_gold_figures(tmp_path, "x") == [(1, 2, 3, 4)]


def test_report_pooled_figures(tmp_path):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.toml").write_text(
        '[[page]]\nid="a"\nbook="b"\nscan=1\ncategories=["text"]\n'
        '[[page]]\nid="b"\nbook="b"\nscan=2\ncategories=["text"]\n'
        '[[page]]\nid="c"\nbook="b"\nscan=3\ncategories=["text"]\n', encoding="utf-8")
    for pid in "abc":
        (golden / f"{pid}.md").write_text("текст\n", encoding="utf-8")
        (golden / f"{pid}.png").write_bytes(b"")
    (golden / "a.figures.json").write_text(json.dumps({"figures": [[0, 0, 100, 100], [200, 0, 300, 100]]}))
    (golden / "b.figures.json").write_text(json.dumps({"figures": [[0, 0, 50, 50]]}))
    # page c has no figures.json -> skipped
    runs = tmp_path / "runs"
    for name, layout in [("lay", True), ("nolay", False)]:
        d = runs / name
        d.mkdir(parents=True)
        for pid in "abc":
            blocks = []
            if layout:
                blocks = {"a": [{"category": "Picture", "bbox": [0, 0, 100, 100]},
                                {"category": "Picture", "bbox": [500, 500, 600, 600]}],
                          "b": [{"category": "Picture", "bbox": [0, 0, 50, 50]}],
                          "c": [{"category": "Picture", "bbox": [0, 0, 50, 50]}]}[pid]
            (d / f"{pid}.md").write_text("текст\n", encoding="utf-8")
            (d / f"{pid}.json").write_text(json.dumps(
                {"seconds": 1.0, "error": None, "raw": "", "blocks": blocks}), encoding="utf-8")
    rep = build_report(golden, runs)
    assert "Figures outside tables P/R" in rep and "Sketches in tables R" in rep
    # pooled over a+b: matched 2, n_pred 3, n_gold 3
    lay = next(l for l in rep.splitlines() if l.startswith("| lay "))
    nolay = next(l for l in rep.splitlines() if l.startswith("| nolay "))
    assert "0.67/0.67" in lay
    assert " | — | — | 1.0 | " in nolay and "0.67" not in nolay


def _mk(tmp_path, runs_spec):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.toml").write_text(
        '[[page]]\nid="a"\nbook="b"\nscan=1\ncategories=["text"]\n'
        '[[page]]\nid="b"\nbook="b"\nscan=2\ncategories=["text"]\n', encoding="utf-8")
    for pid in "ab":
        (golden / f"{pid}.md").write_text("текст\n", encoding="utf-8")
        (golden / f"{pid}.png").write_bytes(b"")
        (golden / f"{pid}.figures.json").write_text(json.dumps({"figures": [[0, 0, 50, 50]]}))
    pic = [{"category": "Picture", "bbox": [0, 0, 50, 50]}]
    for name, pages in runs_spec.items():
        d = tmp_path / "runs" / name
        d.mkdir(parents=True)
        for pid, (blocks, err) in pages.items():
            (d / f"{pid}.md").write_text("текст\n", encoding="utf-8")
            (d / f"{pid}.json").write_text(json.dumps(
                {"seconds": 1.0, "error": err, "raw": "", "blocks": blocks}), encoding="utf-8")
    return golden, tmp_path / "runs", pic


def test_layout_model_failed_page_counts_as_zero(tmp_path):
    pic = [{"category": "Picture", "bbox": [0, 0, 50, 50]}]
    golden, runs, _ = _mk(tmp_path, {"m": {"a": (pic, None), "b": ([], "x")}})
    line = next(l for l in build_report(golden, runs).splitlines() if l.startswith("| m "))
    assert "1.00/0.50" in line


def test_layout_model_missing_page_counts_as_zero(tmp_path):
    pic = [{"category": "Picture", "bbox": [0, 0, 50, 50]}]
    golden, runs, _ = _mk(tmp_path, {"m": {"a": (pic, None)}})
    line = next(l for l in build_report(golden, runs).splitlines() if l.startswith("| m "))
    assert "1.00/0.50" in line


def test_errored_page_with_blocks_still_used(tmp_path):
    pic = [{"category": "Picture", "bbox": [0, 0, 50, 50]}]
    golden, runs, _ = _mk(tmp_path, {"m": {"a": (pic, "truncated"), "b": (pic, "looping")}})
    line = next(l for l in build_report(golden, runs).splitlines() if l.startswith("| m "))
    assert "1.00/1.00" in line


def test_in_table_split_geometry():
    from techbookocr.eval.figures import in_table, split_by_tables, table_boxes

    tables = table_boxes([{"category": "Table", "bbox": [0, 100, 200, 300]}, {"category": "Text", "bbox": [0, 0, 5, 5]}])
    assert tables == [(0, 100, 200, 300)]
    assert in_table((10, 110, 30, 130), tables) and not in_table((10, 10, 30, 30), tables)
    # center is inside even though the box sticks out
    assert in_table((150, 250, 250, 350), tables) is True
    out, inn = split_by_tables([(10, 110, 30, 130), (10, 10, 30, 30)], tables)
    assert out == [(10, 10, 30, 30)] and inn == [(10, 110, 30, 130)]


def test_report_uses_gold_in_table_split(tmp_path):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.toml").write_text('[[page]]\nid="a"\nbook="b"\nscan=1\ncategories=["table"]\n', encoding="utf-8")
    (golden / "a.md").write_text("текст\n", encoding="utf-8")
    (golden / "a.png").write_bytes(b"")
    # one standalone figure and two sketches in cells (golden mark, not a model table)
    (golden / "a.figures.json").write_text(json.dumps(
        {"figures": [[0, 0, 100, 100], [10, 310, 50, 350], [60, 410, 100, 450]], "in_table": [1, 2]}))
    runs = tmp_path / "runs"
    with_table = [{"category": "Table", "bbox": [0, 300, 200, 500]},
                  {"category": "Picture", "bbox": [0, 0, 100, 100]},
                  {"category": "Picture", "bbox": [10, 310, 50, 350]},
                  {"category": "Picture", "bbox": [500, 500, 600, 600]}]  # extra
    no_table = [{"category": "Picture", "bbox": [10, 310, 50, 350]}]  # sketch found, table not marked up
    for name, blocks in (("m", with_table), ("m2", no_table)):
        d = runs / name
        d.mkdir(parents=True)
        (d / "a.md").write_text("текст\n", encoding="utf-8")
        (d / "a.json").write_text(json.dumps({"seconds": 1.0, "error": None, "raw": "", "blocks": blocks}),
                                  encoding="utf-8")
    rep = build_report(golden, runs)
    m = next(l for l in rep.splitlines() if l.startswith("| m "))
    m2 = next(l for l in rep.splitlines() if l.startswith("| m2 "))
    assert "0.50/1.00" in m and "0.50 (1/2)" in m
    assert "0.00/0.00" in m2 and "0.50 (1/2)" in m2


def test_load_gold_split(tmp_path):
    (tmp_path / "a.figures.json").write_text(json.dumps(
        {"figures": [[0, 0, 10, 10], [20, 0, 30, 10], [40, 0, 50, 10]], "in_table": [0, 2]}))
    assert load_gold_split(tmp_path, "a") == ([(20, 0, 30, 10)], [(0, 0, 10, 10), (40, 0, 50, 10)])
    (tmp_path / "b.figures.json").write_text(json.dumps({"figures": [[0, 0, 10, 10]]}))
    assert load_gold_split(tmp_path, "b") == ([(0, 0, 10, 10)], [])
    assert load_gold_split(tmp_path, "missing") is None


def test_load_gold_split_rejects_bad_indices(tmp_path):
    for bad in ([5], ["0"], [True], 0):
        (tmp_path / "c.figures.json").write_text(json.dumps({"figures": [[0, 0, 10, 10]], "in_table": bad}))
        with pytest.raises(ValueError, match="in_table"):
            load_gold_split(tmp_path, "c")


def test_match_boxes_one_to_one():
    assert match_boxes([(0, 0, 100, 100), (0, 0, 100, 95)], [(0, 0, 100, 100)]) == [(0, 0, 1.0)]
    assert match_boxes([(0, 0, 10, 10)], [(5, 5, 100, 100)]) == []


def test_split_counts_in_table_first():
    gold_out, gold_in = [(0, 0, 100, 100)], [(200, 200, 300, 300), (400, 400, 500, 500)]
    pred = [(0, 0, 100, 100), (200, 200, 300, 300), (900, 900, 950, 950)]
    # one of two sketches found; of the two remaining predictions, one matched the standalone figure
    assert split_figure_counts(pred, gold_out, gold_in) == [1, 2, 1, 1, 2]
    assert figure_cells([1, 2, 1, 1, 2]) == ("0.50/1.00", "0.50 (1/2)")
    assert figure_cells([0, 0, 0, 0, 0]) == ("1.00/1.00", "—")
    assert figure_cells([0, 0, 2, 0, 0]) == ("0.00/0.00", "—")
