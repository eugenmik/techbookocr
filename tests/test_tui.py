from techbookocr.library import Library


def _lib(tmp_path) -> Library:
    lib = Library(tmp_path)
    (tmp_path / "a.djvu").touch()
    lib.add([tmp_path / "a.djvu"])
    lib.add_event("info", "hello event")
    return lib


# --- data.py: read-only probes of state.sqlite / meta.json / nvidia-smi ---


def _state(tmp_path, names=("0001", "0002")):
    """Open/create the work/state.sqlite of book "a" with pages names.

    Creating the DB in tests via BookState is fine: the probes read it only with mode=ro.
    """
    from techbookocr.pipeline.state import BookState, PageEntry

    st = BookState(tmp_path / "a" / "work" / "state.sqlite")
    st.add_pages([PageEntry(name=n, idx=i, scan=i, side="", file=f"pages/{n}.png",
                            width=1000, height=1400) for i, n in enumerate(names)])
    return st


def test_state_path(tmp_path):
    from techbookocr.tui.data import state_path

    assert state_path(tmp_path, "a") == tmp_path / "a" / "work" / "state.sqlite"


def test_progress_missing_state_not_created(tmp_path):
    from techbookocr.tui.data import progress

    lib = _lib(tmp_path)  # book "a" queued, no state.sqlite
    row = lib.book("a")
    assert progress(tmp_path, row) is None
    # processing + per-item stage: open() is actually reached, no file -> None
    lib.set_status("a", "processing", stage="layout")
    assert progress(tmp_path, lib.book("a")) is None
    assert not (tmp_path / "a" / "work" / "state.sqlite").exists()  # the probe does not create the file


def test_progress_layout_and_blocks(tmp_path):
    from techbookocr.models.types import Block
    from techbookocr.tui.data import progress

    lib = _lib(tmp_path)
    lib.set_status("a", "processing", stage="layout")
    with _state(tmp_path) as st:  # 2 pages, layout done on one (1 text block)
        st.set_layout("0001", [Block("Text", "текст", None)], status="done")
    assert progress(tmp_path, lib.book("a")) == (1, 2)
    lib.set_stage("a", "drafts")
    assert progress(tmp_path, lib.book("a")) == (0, 1)  # the only block is still pending
    with _state(tmp_path, ()) as st:
        st.update_block(st.blocks()[0].id, drafts_status="done")
    assert progress(tmp_path, lib.book("a")) == (1, 1)


def test_progress_non_item_stages(tmp_path):
    from techbookocr.tui.data import progress

    lib = _lib(tmp_path)
    with _state(tmp_path) as st:
        st.set_layout("0001", [], status="done")
        st.set_layout("0002", [], status="done")
    lib.set_status("a", "processing", stage="postproc")
    assert progress(tmp_path, lib.book("a")) is None
    lib.set_stage("a", "ingest")
    assert progress(tmp_path, lib.book("a")) is None
    lib.set_stage("a", None)
    assert progress(tmp_path, lib.book("a")) is None


def test_progress_uri_special_chars(tmp_path):
    """`?`/`#`/spaces/unicode in a book name must not break the file:...?mode=ro URI."""
    from techbookocr.library import BookRow
    from techbookocr.pipeline.state import BookState, PageEntry
    from techbookocr.tui.data import progress

    for name in ("a?b", "a#b", "книга тест"):
        with BookState(tmp_path / name / "work" / "state.sqlite") as st:
            st.add_pages([PageEntry(name="0001", idx=0, scan=0, side="", file="pages/0001.png",
                                    width=10, height=10)])
            st.set_layout("0001", [], status="done")
        row = BookRow(path="", name=name, status="processing", priority=0, stage="layout",
                      error=None, added_at="", updated_at="")
        assert progress(tmp_path, row) == (1, 1)


def test_rate_seconds(tmp_path):
    from techbookocr.models.types import Block
    from techbookocr.tui.data import rate_seconds

    path = tmp_path / "a" / "work" / "state.sqlite"
    assert rate_seconds(path, "layout") is None   # no file
    assert not path.exists()                      # the probe does not create the file
    with _state(tmp_path, ("0001", "0002", "0003", "0004")) as st:
        st.set_layout("0001", [], status="done", seconds=1.0)
        st.set_layout("0002", [], status="done", seconds=2.0)
    assert rate_seconds(path, "layout") is None   # <3 values -> None
    with _state(tmp_path, ()) as st:
        st.set_layout("0003", [], status="done", seconds=3.0)
        st.set_layout("0004", [Block("Text", "а", None) for _ in range(3)],
                      status="done", seconds=10.0)
        for b in st.blocks():
            st.update_block(b.id, b_seconds=5.0)
    assert rate_seconds(path, "layout") == 2.5    # median of [1, 2, 3, 10]
    assert rate_seconds(path, "drafts") == 5.0    # median of b_seconds over 3 blocks
    assert rate_seconds(path, "arbiter") is None  # arbiter_seconds is empty
    assert rate_seconds(path, "postproc") is None  # a stage without a seconds column


def test_gpu(monkeypatch):
    import subprocess
    from techbookocr.tui.data import gpu

    def no_smi(*a, **kw):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "run", no_smi)
    assert gpu() is None
    good = subprocess.CompletedProcess(["nvidia-smi"], 0, stdout=b"45, 8192, 12288\n", stderr=b"")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: good)
    assert gpu() == (45, 8192, 12288)
    bad = subprocess.CompletedProcess(["nvidia-smi"], 0, stdout=b"junk\n", stderr=b"")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: bad)
    assert gpu() is None
    nonzero = subprocess.CompletedProcess(["nvidia-smi"], 9, stdout=b"", stderr=b"err")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: nonzero)
    assert gpu() is None


def test_daemon_age(tmp_path):
    from techbookocr.tui.data import daemon_age

    lib = _lib(tmp_path)
    assert daemon_age(lib) is None            # no heartbeat yet
    lib.heartbeat()
    age = daemon_age(lib)
    assert age is not None and 0 <= age < 60
    lib.set_meta("daemon_heartbeat", "2000-01-01T00:00:00")
    assert daemon_age(lib) > 86400            # an old mark -> a large age
    lib.set_meta("daemon_heartbeat", "не дата")
    assert daemon_age(lib) is None            # a broken value -> None


# --- data.py: progress summaries ---


def test_progress_of_stage_seconds_page_count(tmp_path):
    from techbookocr.tui.data import page_count, progress_of, stage_seconds

    st = _state(tmp_path)
    st.add_seconds("layout", 12.5)
    path = tmp_path / "a" / "work" / "state.sqlite"
    assert progress_of(path, "layout") == (0, 2)
    assert progress_of(path, "postproc") is None
    assert stage_seconds(path) == {"layout": 12.5}
    assert page_count(path) == 2
    assert stage_seconds(tmp_path / "missing.sqlite") == {} and page_count(tmp_path / "missing.sqlite") is None
