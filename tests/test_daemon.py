# tests/test_daemon.py
from pathlib import Path

import pytest

from techbookocr.config import Config, LibraryConfig
from techbookocr.daemon import DaemonLock, run_daemon
from techbookocr.library import Library
from techbookocr.pipeline.control import RunStopped
from techbookocr.pipeline.runner import RunOptions
from techbookocr.pipeline.transport import StageAborted


def daemon(tmp_path, run_fn, books=("a.djvu", "b.djvu")):
    lib = Library(tmp_path)
    for i, b in enumerate(books):
        (tmp_path / b).touch()
        lib.add([tmp_path / b])
    # run_fn closes over the test's `lib`, which is bound only after this helper returns;
    # fill the cell in advance so run_fn sees the library during the run
    for var, cell in zip(run_fn.__code__.co_freevars, run_fn.__closure__ or ()):
        if var == "lib":
            cell.cell_contents = lib
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn, sleep=lambda s: None)
    return lib


def test_queue_processed_in_priority_order(tmp_path):
    done = []
    lib = Library(tmp_path)
    for b in ("a.djvu", "b.djvu", "c.djvu"):
        (tmp_path / b).touch(); lib.add([tmp_path / b])
    lib.set_priority("c", 10)
    # stop the daemon after the third book with a stop command pushed by run_fn itself
    def run_fn(book, out_root, cfg, opts, **kw):
        done.append(book.stem)
        if len(done) == 3:
            lib.push_command("stop")
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn, sleep=lambda s: None)
    assert done[0] == "c"
    assert [lib.book(n).status for n in ("a", "b", "c")] == ["done"] * 3
    assert lib.get_meta("daemon_state") == "stopped"


def test_failing_book_does_not_kill_daemon(tmp_path):
    def run_fn(book, out_root, cfg, opts, **kw):
        if book.stem == "a":
            raise StageAborted("server dead", ["0001"])
        lib.push_command("stop")
    lib = daemon(tmp_path, run_fn)
    assert lib.book("a").status == "failed" and "server dead" in lib.book("a").error
    assert lib.book("b").status == "done"


def test_broken_book_written_to_library_report(tmp_path):
    def run_fn(book, out_root, cfg, opts, **kw):
        lib.push_command("stop")
        raise ValueError("corrupt djvu")
    lib = daemon(tmp_path, run_fn, books=("a.djvu",))
    assert lib.book("a").status == "failed"
    report = (tmp_path / "library_report.md").read_text()
    assert "a.djvu" in report and "corrupt" in report


def test_stale_commands_and_reset_processing(tmp_path):
    lib = Library(tmp_path)
    (tmp_path / "a.djvu").touch(); lib.add([tmp_path / "a.djvu"])
    lib.set_status("a", "processing")          # "the previous daemon died"
    lib.push_command("stop")                    # stale: must not kill the new daemon
    def run_fn(book, out_root, cfg, opts, **kw):
        lib.push_command("stop")                # a fresh stop ends the loop
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn, sleep=lambda s: None)
    assert lib.book("a").status == "done"
    assert any("stale" in e.message for e in lib.events())


def test_daemon_lock_exclusive(tmp_path):
    from techbookocr.config import ConfigError
    with DaemonLock(tmp_path):
        with pytest.raises(ConfigError):
            with DaemonLock(tmp_path):
                pass


def test_stop_after_cpu_stage_book_completes(tmp_path):
    """stop arrives while the book is already being assembled (control is not polled): the book is assembled, the daemon stops after."""
    def run_fn(book, out_root, cfg, opts, **kw):
        lib.push_command("stop")   # run_fn does not call ctl.poll: stop is noticeable only from outside
    lib = daemon(tmp_path, run_fn, books=("a.djvu",))
    assert lib.book("a").status == "done"
    assert lib.get_meta("daemon_state") == "stopped"


def test_run_stopped_skipped_marks_book(tmp_path):
    """skip on a book in progress: RunStopped('skipped') -> the book is skipped, the daemon stops on stop."""
    def run_fn(book, out_root, cfg, opts, **kw):
        lib.push_command("stop")   # the daemon will see stopping on the next tick and exit
        raise RunStopped("skipped")
    lib = daemon(tmp_path, run_fn, books=("a.djvu",))
    assert lib.book("a").status == "skipped"
    assert lib.get_meta("daemon_state") == "stopped"


def test_run_stopped_queued_requeues_book(tmp_path):
    """stop on a book in progress: RunStopped('queued') -> the book goes back to the queue, the daemon stops."""
    def run_fn(book, out_root, cfg, opts, **kw):
        lib.push_command("stop")
        raise RunStopped("queued")
    lib = daemon(tmp_path, run_fn, books=("a.djvu",))
    assert lib.book("a").status == "queued"
    assert lib.get_meta("daemon_state") == "stopped"


def test_done_book_auto_summarized(tmp_path):
    """auto_summarize (on by default): after done the daemon calls summarize_fn with the root and the book name."""
    seen = []
    lib = Library(tmp_path)
    (tmp_path / "a.djvu").touch(); lib.add([tmp_path / "a.djvu"])
    def run_fn(book, out_root, cfg, opts, **kw):
        lib.push_command("stop")
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn,
               summarize_fn=lambda root, name, c: seen.append(name), sleep=lambda s: None)
    assert seen == ["a"] and lib.book("a").status == "done"


def test_summarize_failure_keeps_done(tmp_path):
    """A summary failure is a warn event, the book stays done, the daemon does not crash."""
    def run_fn(book, out_root, cfg, opts, **kw):
        lib.push_command("stop")
    def boom(root, name, cfg):
        raise RuntimeError("no model")
    lib = Library(tmp_path)
    (tmp_path / "a.djvu").touch(); lib.add([tmp_path / "a.djvu"])
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn,
               summarize_fn=boom, sleep=lambda s: None)
    assert lib.book("a").status == "done"
    assert any(e.level == "warn" and "summary" in e.message for e in lib.events())


def test_auto_summarize_off(tmp_path):
    """auto_summarize=false: summarize_fn is not called."""
    seen = []
    lib = Library(tmp_path)
    (tmp_path / "a.djvu").touch(); lib.add([tmp_path / "a.djvu"])
    def run_fn(book, out_root, cfg, opts, **kw):
        lib.push_command("stop")
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0, auto_summarize=False))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn,
               summarize_fn=lambda *a: seen.append(a), sleep=lambda s: None)
    assert seen == []


def test_keyboard_interrupt_requeues_book(tmp_path):
    """Ctrl+C during work: the book -> queued (resumable), the exception propagates, daemon_state -> stopped."""
    lib = Library(tmp_path)
    (tmp_path / "a.djvu").touch(); lib.add([tmp_path / "a.djvu"])
    def run_fn(book, out_root, cfg, opts, **kw):
        raise KeyboardInterrupt
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    with pytest.raises(KeyboardInterrupt):
        run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn, sleep=lambda s: None)
    assert lib.book("a").status == "queued"
    assert lib.get_meta("daemon_state") == "stopped"


def test_run_until_pauses_after_target(tmp_path):
    """meta run_until=<book>: the daemon processes it and pauses, leaving the rest alone."""
    done = []
    lib = Library(tmp_path)
    for b in ("a.djvu", "b.djvu", "c.djvu"):
        (tmp_path / b).touch(); lib.add([tmp_path / b])
    lib.set_meta("run_until", "a")
    def run_fn(book, out_root, cfg, opts, **kw):
        done.append(book.stem)
        lib.push_command("stop")   # while paused the daemon handles stop and exits
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn, sleep=lambda s: None)
    assert done == ["a"]
    assert lib.book("a").status == "done"
    assert lib.book("b").status == "queued"
    assert lib.get_meta("run_until") is None
    assert lib.get_meta("daemon_state") == "stopped"


def test_run_until_mid_queue(tmp_path):
    """run_until in the middle of the queue: earlier books run as usual, pause after the target."""
    done = []
    lib = Library(tmp_path)
    for b in ("a.djvu", "b.djvu", "c.djvu"):
        (tmp_path / b).touch(); lib.add([tmp_path / b])
    lib.set_meta("run_until", "b")
    def run_fn(book, out_root, cfg, opts, **kw):
        done.append(book.stem)
        if book.stem == "b":
            lib.push_command("stop")
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn, sleep=lambda s: None)
    assert done == ["a", "b"]
    assert lib.book("c").status == "queued"


def test_run_until_gone_target_cleared(tmp_path):
    """run_until on a nonexistent book: the flag is cleared, the queue runs in the usual order."""
    done = []
    lib = Library(tmp_path)
    (tmp_path / "a.djvu").touch(); lib.add([tmp_path / "a.djvu"])
    lib.set_meta("run_until", "ghost")
    def run_fn(book, out_root, cfg, opts, **kw):
        done.append(book.stem)
        lib.push_command("stop")
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn, sleep=lambda s: None)
    assert done == ["a"]
    assert lib.get_meta("run_until") is None


def test_run_until_skipped_target_cleared(tmp_path):
    """The run_until target left queued/processing (skip) -> the flag is cleared, no pause."""
    done = []
    lib = Library(tmp_path)
    for b in ("a.djvu", "b.djvu"):
        (tmp_path / b).touch(); lib.add([tmp_path / b])
    lib.set_meta("run_until", "b")
    lib.set_status("b", "skipped")
    def run_fn(book, out_root, cfg, opts, **kw):
        done.append(book.stem)
        lib.push_command("stop")
    cfg = Config(library=LibraryConfig(command_poll_s=0, idle_poll_s=0))
    run_daemon(lib, cfg, RunOptions(), out_root=tmp_path, run_book_fn=run_fn, sleep=lambda s: None)
    assert done == ["a"]
    assert lib.get_meta("run_until") is None


def test_run_until_cleared_by_daemon_start_semantics(tmp_path):
    """run_until is state in meta: a new setting overwrites the old one (the last Run wins)."""
    lib = Library(tmp_path)
    lib.set_meta("run_until", "a")
    lib.set_meta("run_until", "b")
    assert lib.get_meta("run_until") == "b"
    lib.del_meta("run_until")
    assert lib.get_meta("run_until") is None
