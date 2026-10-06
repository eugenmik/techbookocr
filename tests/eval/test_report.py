import json

from techbookocr.eval.report import build_report


def test_report_ranks_models(tmp_path):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.toml").write_text(
        '[[page]]\nid="a"\nbook="b"\nscan=1\ncategories=["text"]\n'
        '[[page]]\nid="t"\nbook="b"\nscan=2\ncategories=["table"]\n', encoding="utf-8")
    for pid, md in {"a": "Чугун марки СЧ20 содержит 3,2% углерода.\n",
                    "t": "<table><tr><td>1</td><td>2</td></tr></table>\n"}.items():
        (golden / f"{pid}.md").write_text(md, encoding="utf-8")
        (golden / f"{pid}.png").write_bytes(b"")
    runs = tmp_path / "runs"
    for key, a_md, err in [("good", "Чугун марки СЧ20 содержит 3,2% углерода.\n", None),
                           ("bad", "Чугун марки CЧ2О содержит 3,7% углерода.\n", "looping")]:
        d = runs / key
        d.mkdir(parents=True)
        (d / "a.md").write_text(a_md, encoding="utf-8")
        (d / "a.json").write_text(json.dumps({"seconds": 2.0, "error": err, "raw": "", "blocks": []}), encoding="utf-8")
        (d / "t.md").write_text("<table><tr><td>1</td><td>2</td></tr></table>\n", encoding="utf-8")
        (d / "t.json").write_text(json.dumps({"seconds": 4.0, "error": None, "raw": "", "blocks": []}), encoding="utf-8")
        (d / "_meta.json").write_text(json.dumps({"peak_vram_mib": 9000}), encoding="utf-8")
    rep = build_report(golden, runs)
    assert rep.index("| good") < rep.index("| bad")
    assert "Numbers F1" in rep and "TEDS" in rep and "s/page" in rep
    assert "## By category" in rep
    assert "bad: 1 errors" in rep


def test_missing_pages_dont_outrank_complete(tmp_path):
    """Test that incomplete models don't outrank complete ones even if alphabetically first.
    Rename to a_incomplete vs z_complete to verify scoring matters, not just sort order."""
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.toml").write_text(
        '[[page]]\nid="a"\nbook="b"\nscan=1\ncategories=["text"]\n'
        '[[page]]\nid="b"\nbook="b"\nscan=2\ncategories=["text"]\n', encoding="utf-8")
    for pid in ["a", "b"]:
        (golden / f"{pid}.md").write_text("Хорошая страница\n", encoding="utf-8")
        (golden / f"{pid}.png").write_bytes(b"")

    runs = tmp_path / "runs"

    # Model z_complete: has both pages with perfect scores
    # Alphabetically after a_incomplete, but should rank first due to completeness
    d_complete = runs / "z_complete"
    d_complete.mkdir(parents=True)
    for pid in ["a", "b"]:
        (d_complete / f"{pid}.md").write_text("Хорошая страница\n", encoding="utf-8")
        (d_complete / f"{pid}.json").write_text(json.dumps({"seconds": 1.0, "error": None, "raw": "", "blocks": []}), encoding="utf-8")
    (d_complete / "_meta.json").write_text(json.dumps({"peak_vram_mib": 5000}), encoding="utf-8")

    # Model a_incomplete: only one page (its best), missing the other
    # Would sort first alphabetically, but should rank last due to missing page
    d_incomplete = runs / "a_incomplete"
    d_incomplete.mkdir(parents=True)
    (d_incomplete / "a.md").write_text("Хорошая страница\n", encoding="utf-8")
    (d_incomplete / "a.json").write_text(json.dumps({"seconds": 1.0, "error": None, "raw": "", "blocks": []}), encoding="utf-8")
    (d_incomplete / "_meta.json").write_text(json.dumps({"peak_vram_mib": 5000}), encoding="utf-8")

    rep = build_report(golden, runs)
    # z_complete should rank before a_incomplete despite alphabetical order
    # This proves scoring (missing pages) matters, not just sort order
    assert rep.index("| z_complete") < rep.index("| a_incomplete"), \
        "Missing-page scoring should outrank alphabetical order"
    # a_incomplete should report 1 missing page
    assert "a_incomplete: " in rep and "1 pages missing" in rep


def test_meta_missing_seconds_or_error_counts_as_error(tmp_path):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.toml").write_text('[[page]]\nid="a"\nbook="b"\nscan=1\ncategories=["text"]\n', encoding="utf-8")
    (golden / "a.md").write_text("Текст\n", encoding="utf-8")
    (golden / "a.png").write_bytes(b"")
    d = tmp_path / "runs" / "m"
    d.mkdir(parents=True)
    (d / "a.md").write_text("Текст\n", encoding="utf-8")
    (d / "a.json").write_text(json.dumps({"raw": "", "blocks": []}), encoding="utf-8")
    rep = build_report(golden, tmp_path / "runs")
    assert "m: 1 errors" in rep
