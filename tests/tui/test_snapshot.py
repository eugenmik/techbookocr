import json
from pathlib import Path

from techbookocr.library import Library


def _lib(tmp_path, names=("a",)) -> Library:
    lib = Library(tmp_path)
    for n in names:
        (tmp_path / f"{n}.djvu").touch()
    lib.add([tmp_path / f"{n}.djvu" for n in names])
    return lib


def _no_probes(monkeypatch):
    monkeypatch.setattr("techbookocr.tui.data.gpu", lambda: (97, 11000, 12288))
    monkeypatch.setattr("techbookocr.tui.snapshot.model_info", lambda: None)
    monkeypatch.setattr("techbookocr.tui.snapshot.scan_count", lambda p: 100)


def _done_book(root: Path, name: str, scans: int, seconds: float, with_timings=True):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    meta = {"pages": scans, "page_map": [{"scan": f"{i:04d}", "printed": None} for i in range(scans)]}
    if with_timings:
        meta["timings"] = {"layout": seconds * 0.6, "arbiter": seconds * 0.4}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_snapshot_shape(tmp_path, monkeypatch):
    from techbookocr.tui.snapshot import snapshot

    _no_probes(monkeypatch)
    lib = _lib(tmp_path, ("a", "b"))
    lib.add_event("info", "hello")
    s = snapshot(lib)
    assert set(s) == {"daemon", "root", "counts", "books", "current", "forecast", "gpu", "model", "events"}
    assert s["daemon"]["alive"] is False and s["daemon"]["state"] == "never ran"
    assert s["counts"]["queued"] == 2
    assert s["books"][0] == {"name": "a", "status": "queued", "stage": None, "priority": 0, "error": None,
                             "progress": None, "scans": 100}
    assert s["gpu"] == {"util": 97, "used_mib": 11000, "total_mib": 12288}
    assert s["events"][-1]["message"] == "hello"
    json.dumps(s)  # JSON-compatible


def test_snapshot_fills_scans_within_time_budget(tmp_path, monkeypatch):
    from techbookocr.tui import snapshot as snap

    _no_probes(monkeypatch)
    lib = _lib(tmp_path, ("a", "b", "c", "d", "e"))
    t = [0.0]

    def slow_count(path):
        t[0] += 0.1                      # each book "opens" in 0.1 s
        return 10
    monkeypatch.setattr(snap, "scan_count", slow_count)
    monkeypatch.setattr(snap.time, "monotonic", lambda: t[0])
    snap.snapshot(lib)
    assert sum(lib.has_scans(n) for n in "abcde") == 3        # budget 0.3 s


def test_fill_scans_counts_many_when_fast(tmp_path, monkeypatch):
    from techbookocr.tui import snapshot as snap

    _no_probes(monkeypatch)
    lib = _lib(tmp_path, tuple("abcdefghij"))
    monkeypatch.setattr(snap, "scan_count", lambda p: 5)
    snap.snapshot(lib)
    assert all(lib.has_scans(n) for n in "abcdefghij")


def test_fill_scans_writes_sentinel_before_counting(tmp_path, monkeypatch):
    from techbookocr.tui import snapshot as snap

    lib = _lib(tmp_path, ("a",))
    seen = []

    def probe(path):
        seen.append((lib.has_scans("a"), lib.scans("a")))
        return 7
    monkeypatch.setattr(snap, "scan_count", probe)
    snap.fill_scans(lib, lib.books())
    assert seen == [(True, None)] and lib.scans("a") == 7   # "?" was already set: a failure will not loop the snapshots


def test_forecast_uses_done_books(tmp_path, monkeypatch):
    from techbookocr.tui.snapshot import forecast

    lib = _lib(tmp_path, ("q1", "q2", "d1", "d2"))
    lib.set_scans("q1", 100)
    lib.set_scans("q2", 300)
    for n, sec in (("d1", 1000.0), ("d2", 3000.0)):
        lib.set_status(n, "done")
        _done_book(tmp_path, n, 100, sec)          # 10 and 30 s/frame -> median 20
    lib.set_scans("d1", 100)
    f = forecast(lib, lib.books(), None, today=lib.book("d1").updated_at[:10])
    assert f["queued_books"] == 2 and f["scans"] == 400 and f["unknown_scans"] == 0
    assert f["s_per_scan"] == 20.0 and f["basis_books"] == 2
    assert f["seconds"] == 8000.0
    assert f["done_today"] == {"books": 2, "scans": 100}


def test_forecast_without_timings_is_null(tmp_path):
    from techbookocr.tui.snapshot import forecast

    lib = _lib(tmp_path, ("q", "d"))
    lib.set_status("d", "done")
    _done_book(tmp_path, "d", 10, 100.0, with_timings=False)
    f = forecast(lib, lib.books(), None)
    assert f["seconds"] is None and f["s_per_scan"] is None and f["basis_books"] == 0
    assert f["unknown_scans"] == 1


def test_forecast_falls_back_to_quality_md(tmp_path):
    from techbookocr.tui.snapshot import forecast

    lib = _lib(tmp_path, ("q", "d"))
    lib.set_scans("q", 10)
    lib.set_status("d", "done")
    _done_book(tmp_path, "d", 10, 0, with_timings=False)
    (tmp_path / "d" / "quality.md").write_text(
        "# q\n\n## Время по этапам\n\n| Этап | Секунд | с/стр |\n|---|---|---|\n"
        "| layout | 80 | 8.0 |\n| arbiter | 20 | 2.0 |\n\n## Сбои разметки\n\n- нет\n", encoding="utf-8")
    f = forecast(lib, lib.books(), None)
    assert f["s_per_scan"] == 10.0 and f["seconds"] == 100.0


def test_timings_from_quality_english():
    from techbookocr.tui.snapshot import timings_from_quality

    text = "## Time per stage\n\n| Stage | Seconds | s/page |\n|---|---|---|\n| layout | 20220 | 26.9 |\n"
    assert timings_from_quality(text) == {"layout": 20220.0}
    assert timings_from_quality("garbage") == {}


def test_model_info_parses_docker(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    from techbookocr.tui.snapshot import model_info

    out = "techbookocr-qwen9b_arbiter\t2026-01-01 10:00:00 +0000 UTC\n"
    info = model_info(run=lambda *a, **k: SimpleNamespace(returncode=0, stdout=out))
    assert info["key"] == "qwen9b_arbiter" and info["container"] == "techbookocr-qwen9b_arbiter"
    assert info["up_s"] is not None and info["up_s"] > 0
    assert model_info(run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="")) is None

    def boom(*a, **k):
        raise FileNotFoundError("docker")
    assert model_info(run=boom) is None


def test_log_tail(tmp_path):
    from techbookocr.tui.snapshot import log_tail

    assert log_tail(tmp_path, 5) == []
    (tmp_path / "daemon.log").write_text("\n".join(f"line {i}" for i in range(100)) + "\n", encoding="utf-8")
    assert log_tail(tmp_path, 3) == ["line 97", "line 98", "line 99"]


def test_current_processing_book(tmp_path, monkeypatch):
    from techbookocr.pipeline.state import BookState, PageEntry
    from techbookocr.tui.snapshot import snapshot

    _no_probes(monkeypatch)
    lib = _lib(tmp_path, ("a?#",))                      # special characters in the name do not break the probes
    lib.set_status("a?#", "processing")
    lib.set_stage("a?#", "layout")
    st = BookState(tmp_path / "a?#" / "work" / "state.sqlite")
    st.add_pages([PageEntry(name=f"{i:04d}", idx=i, scan=i, side="", file="", width=10, height=10)
                  for i in range(4)])
    st.close()
    s = snapshot(lib)
    assert s["books"][0]["progress"] == [0, 4]
    assert s["current"]["name"] == "a?#" and s["current"]["progress"] == [0, 4]


def test_done_rate_cached_until_file_changes(tmp_path, monkeypatch):
    from techbookocr.tui import snapshot as snap

    snap._RATE_CACHE.clear()
    lib = _lib(tmp_path, ("d",))
    lib.set_status("d", "done")
    _done_book(tmp_path, "d", 10, 100.0)
    calls = []
    real_json, real_text = snap.read_json, snap.read_text
    monkeypatch.setattr(snap, "read_json", lambda p: calls.append(p) or real_json(p))
    monkeypatch.setattr(snap, "read_text", lambda p: calls.append(p) or real_text(p))
    assert snap.done_rate(tmp_path, lib.books()) == (10.0, 1)
    n = len(calls)
    assert n >= 1
    assert snap.done_rate(tmp_path, lib.books()) == (10.0, 1)
    assert len(calls) == n                              # the second call did not read the files
    _done_book(tmp_path, "d", 10, 200.0)
    import os
    st = (tmp_path / "d" / "meta.json").stat()
    os.utime(tmp_path / "d" / "meta.json", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert snap.done_rate(tmp_path, lib.books()) == (20.0, 1)


def test_corrupt_quality_md_does_not_break_forecast(tmp_path, monkeypatch):
    from techbookocr.tui import snapshot as snap

    snap._RATE_CACHE.clear()
    _no_probes(monkeypatch)
    lib = _lib(tmp_path, ("q", "d1", "d2"))
    lib.set_scans("q", 10)
    for n in ("d1", "d2"):
        lib.set_status(n, "done")
        _done_book(tmp_path, n, 10, 0, with_timings=False)
    (tmp_path / "d1" / "quality.md").write_bytes(b"## Time per stage\n\xff\xfe\n")
    (tmp_path / "d2" / "quality.md").write_text(
        "## Time per stage\n\n| Stage | Seconds |\n|---|---|\n| layout | 1.2.3 |\n| x | . |\n", encoding="utf-8")
    f = snap.forecast(lib, lib.books(), None)
    assert f["s_per_scan"] is None and f["basis_books"] == 0
    assert snap.snapshot(lib)["forecast"]["seconds"] is None
