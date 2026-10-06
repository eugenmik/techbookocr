import json

import pytest

from techbookocr.library import Library

QUALITY = """# Quality

## Time per stage

| Stage | Seconds | s/page |
|---|---|---|
| layout | 600 | 6.0 |
| arbiter | 300 | 3.0 |

## Layout failures

- none

## Rejected and failed arbiter answers

- 0004L (p. 8), block 2 (table): rejected, cer 0.629 → fallback_a

## Failed blocks

- none
"""


def _lib(tmp_path, name="a") -> Library:
    lib = Library(tmp_path)
    (tmp_path / f"{name}.djvu").touch()
    lib.add([tmp_path / f"{name}.djvu"])
    lib.set_scans(name, 100)
    return lib


def test_done_book_from_meta_and_quality(tmp_path):
    from techbookocr.tui.snapshot import book_detail

    lib = _lib(tmp_path)
    lib.set_status("a", "done")
    d = tmp_path / "a"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"pages": 100, "lang": ["ru"], "mode": "fast",
                                             "timings": {"layout": 600.0, "arbiter": 300.0}}), encoding="utf-8")
    (d / "quality.md").write_text(QUALITY, encoding="utf-8")
    r = book_detail(lib, "a")
    assert r["info"]["kind"] == "djvu" and r["info"]["lang"] == "ru" and r["info"]["pages"] == 100
    assert [(s["stage"], s["status"], s["s_per_page"]) for s in r["stages"]] == \
        [("layout", "done", 6.0), ("arbiter", "done", 3.0)]
    assert r["issues"] == ["0004L (p. 8), block 2 (table): rejected, cer 0.629 → fallback_a"]
    assert r["quality_md"].startswith("# Quality")
    json.dumps(r)


def test_processing_book_from_state(tmp_path):
    from techbookocr.models.types import Block
    from techbookocr.pipeline.state import BookState, PageEntry
    from techbookocr.tui.snapshot import book_detail

    lib = _lib(tmp_path)
    lib.set_status("a", "processing")
    lib.set_stage("a", "layout")
    st = BookState(tmp_path / "a" / "work" / "state.sqlite")
    st.add_pages([PageEntry(name=f"{i:04d}", idx=i, scan=i, side="", file="", width=10, height=10)
                  for i in range(4)])
    st.set_layout("0000", [Block("Text", "x", (0, 0, 5, 5))], status="failed", error="looping")
    st.add_seconds("layout", 40.0)
    st.close()
    r = book_detail(lib, "a")
    layout = r["stages"][0]
    assert layout["stage"] == "layout" and layout["status"] == "running"
    assert layout["progress"] == [1, 4] and layout["seconds"] == 40.0 and layout["s_per_page"] == 10.0
    assert [s["status"] for s in r["stages"][1:]] == ["pending"] * 6
    assert r["issues"] == ["0000: layout failed — looping"]
    assert r["quality_md"] is None


def test_queued_book_and_missing(tmp_path):
    from techbookocr.tui.snapshot import book_detail

    lib = _lib(tmp_path)
    r = book_detail(lib, "a")
    assert r["stages"] == [] and r["issues"] == [] and r["info"]["scans"] == 100
    with pytest.raises(KeyError):
        book_detail(lib, "nope")


def test_issues_russian_headings():
    from techbookocr.tui.snapshot import issues_from_quality

    text = "## Сбои разметки\n\n- 0003 (с. 5): looping\n\n## Сбойные блоки\n\n- нет\n"
    assert issues_from_quality(text) == ["0003 (с. 5): looping"]
