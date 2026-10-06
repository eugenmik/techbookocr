import sys
from pathlib import Path

from techbookocr.library import Library


def _lib(tmp_path, names=("a",)) -> Library:
    lib = Library(tmp_path)
    for n in names:
        (tmp_path / f"{n}.djvu").touch()
    lib.add([tmp_path / f"{n}.djvu" for n in names])
    return lib


def _alive(monkeypatch, lib, alive=True):
    monkeypatch.setattr(lib, "daemon_alive", lambda: alive)


def test_book_action_dead_daemon_applies_now(tmp_path):
    from techbookocr.tui.actions import book_action

    lib = _lib(tmp_path)
    assert book_action(lib, "skip", "a") == "skip a → skipped"
    assert lib.book("a").status == "skipped"
    assert book_action(lib, "skip", "nope") == "no book nope"


def test_book_action_alive_pushes_command(tmp_path, monkeypatch):
    from techbookocr.tui.actions import book_action

    lib = _lib(tmp_path)
    _alive(monkeypatch, lib)
    assert book_action(lib, "retry", "a") == "command retry a queued"
    assert [c.command for c in lib.poll_commands()] == ["retry"]


def test_book_action_db_error_is_message(tmp_path, monkeypatch):
    import sqlite3

    from techbookocr.tui.actions import book_action

    lib = _lib(tmp_path)

    def boom():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(lib, "daemon_alive", boom)
    assert book_action(lib, "skip", "a") == "error skip a: database is locked"


def test_bump_and_missing_book(tmp_path):
    from techbookocr.tui.actions import bump

    lib = _lib(tmp_path)
    assert bump(lib, ["a", "gone"], +2) == ["a: priority 2", "no book gone"]
    assert lib.book("a").priority == 2


def test_run_books_dead_daemon(tmp_path):
    from techbookocr.tui.actions import run_books

    lib = _lib(tmp_path, ("a", "b"))
    lib.set_priority("b", 5)
    started = []
    msgs = run_books(lib, ["a"], tmp_path / "c.toml", start=lambda l, c: started.append(c) or "started")
    assert lib.book("a").priority == 6 and lib.get_meta("run_until") == "a"
    assert started == [tmp_path / "c.toml"]
    assert msgs[-1] == "a → daemon starting"


def test_run_books_failed_retried_and_paused_resumed(tmp_path, monkeypatch):
    from techbookocr.tui.actions import run_books

    lib = _lib(tmp_path, ("a",))
    lib.set_status("a", "failed", error="x")
    msgs = run_books(lib, ["a"], tmp_path / "c.toml", start=lambda l, c: "started")
    assert lib.book("a").status == "queued"
    lib.set_meta("daemon_state", "paused")
    _alive(monkeypatch, lib)
    msgs = run_books(lib, ["a"], tmp_path / "c.toml", start=lambda l, c: "unexpected")
    assert "resume" in [c.command for c in lib.poll_commands()]
    assert msgs[-1] == "a → resuming"


def test_run_books_nothing(tmp_path):
    from techbookocr.tui.actions import run_books

    lib = _lib(tmp_path)
    lib.set_status("a", "done")
    assert run_books(lib, ["a"], tmp_path / "c.toml") == ["nothing to run — selected books are done"]
    assert run_books(lib, [], tmp_path / "c.toml") == ["select a book first — cursor or space to mark"]


def test_daemon_toggle_gate(tmp_path, monkeypatch):
    from techbookocr.tui.actions import daemon_toggle

    lib = _lib(tmp_path)
    assert daemon_toggle(lib) == ["daemon is not running"]
    _alive(monkeypatch, lib)
    lib.set_meta("daemon_state", "stopping")
    assert daemon_toggle(lib) == ["daemon is stopping: pause/resume unavailable"]
    assert lib.poll_commands() == []                 # pause is not written in stopping
    lib.set_meta("daemon_state", "running")
    assert daemon_toggle(lib) == ["command pause queued"]


def test_daemon_start_clears_run_until(tmp_path):
    from techbookocr.tui.actions import daemon_start

    lib = _lib(tmp_path)
    lib.set_meta("run_until", "a")
    assert daemon_start(lib, tmp_path / "c.toml", start=lambda l, c: "daemon started") == ["daemon started"]
    assert lib.get_meta("run_until") is None


def test_start_daemon_argv_and_failure(tmp_path):
    from techbookocr.tui.actions import start_daemon

    lib = _lib(tmp_path)
    calls = []
    msg = start_daemon(lib, tmp_path / "c.toml", popen=lambda argv, **kw: calls.append(argv),
                       wait_s=0.0, sleep=lambda s: None)
    assert calls[0][:5] == [sys.executable, "-m", "techbookocr", "daemon", "--out"]
    assert calls[0][-2:] == ["--config", str((tmp_path / "c.toml").resolve())]
    assert msg == f"daemon failed to start — see {tmp_path / 'daemon.log'}"


def test_add_paths(tmp_path):
    from techbookocr.tui.actions import add_paths

    lib = Library(tmp_path / "lib")
    (tmp_path / "x.djvu").write_bytes(b"junk")
    (tmp_path / "notes.txt").touch()
    res = add_paths(lib, [tmp_path / "x.djvu", tmp_path / "notes.txt"])
    assert res["added"] == ["x"] and len(res["skipped"]) == 1
    assert not lib.has_scans("x")                         # the snapshot computes scans, not the add request
    assert res["messages"] == ["added: 1, skipped: 1 — daemon is not running; press d to process the queue"]


def test_add_paths_does_not_count_scans(tmp_path, monkeypatch):
    from techbookocr.tui.actions import add_paths

    def boom(path):
        raise AssertionError("scan_count в запросе add")
    monkeypatch.setattr("techbookocr.ingest.source.scan_count", boom)
    lib = Library(tmp_path / "lib")
    (tmp_path / "x.djvu").write_bytes(b"junk")
    assert add_paths(lib, [tmp_path / "x.djvu"])["added"] == ["x"]


def test_add_paths_caps_skipped_list(tmp_path):
    from techbookocr.tui.actions import add_paths

    lib = Library(tmp_path / "lib")
    for i in range(30):
        (tmp_path / f"n{i}.txt").touch()
    (tmp_path / "x.djvu").write_bytes(b"junk")
    res = add_paths(lib, [tmp_path / f"n{i}.txt" for i in range(30)] + [tmp_path / "x.djvu"])
    assert res["added"] == ["x"] and len(res["skipped"]) == 20 and res["skipped_total"] == 30
    assert res["messages"][0].startswith("added: 1, skipped: 30")
