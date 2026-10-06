# tests/test_control.py
import pytest

from techbookocr.library import Library
from techbookocr.pipeline.control import Control, RunStopped, drain_commands


def make_lib(root):
    lib = Library(root)
    (root / "vol.djvu").touch()
    lib.add([root / "vol.djvu"])
    lib.set_status("vol", "processing")
    return lib


def ctl(lib, book="vol", **kw):
    return Control(lib, book, poll_s=0, **kw)


def test_pause_waits_until_resume(tmp_path):
    lib = make_lib(tmp_path)
    lib.set_meta("daemon_state", "running")
    lib.push_command("pause")
    c = ctl(lib, sleep=lambda s: lib.push_command("resume"))
    c.poll()  # pause -> wait loop -> sleep pushes resume -> exits without an exception
    assert lib.get_meta("daemon_state") == "running"


def test_stop_and_skip_raise(tmp_path):
    lib = make_lib(tmp_path)
    lib.push_command("stop")
    with pytest.raises(RunStopped) as e:
        ctl(lib).poll()
    assert e.value.outcome == "queued"

    lib2 = make_lib(tmp_path / "o2")   # Library.__init__ creates the root
    lib2.push_command("skip", book="vol")
    with pytest.raises(RunStopped) as e2:
        ctl(lib2).poll()
    assert e2.value.outcome == "skipped"


def test_skip_other_and_wrong_status(tmp_path):
    lib = make_lib(tmp_path)
    (tmp_path / "other.djvu").touch(); lib.add([tmp_path / "other.djvu"])
    lib.push_command("skip", book="other")
    lib.push_command("retry", book="other")   # skipped → queued
    lib.push_command("skip", book="missing")  # no such book -> event, no crash
    ctl(lib).poll()
    assert lib.book("other").status == "queued"  # retry after skip put it back
    assert any("missing" in e.message for e in lib.events())


def test_drain_consumes(tmp_path):
    lib = make_lib(tmp_path)
    lib.push_command("pause")
    assert drain_commands(lib, None) is False
    assert lib.poll_commands() == []


def test_run_until_command_sets_meta(tmp_path):
    """run_until <book> on queued/processing: meta; on done: an error event, no meta."""
    from techbookocr.library import Command
    from techbookocr.pipeline.control import apply_command
    from datetime import datetime

    lib = make_lib(tmp_path)                       # vol → processing
    ts = datetime.now().isoformat(timespec="seconds")
    apply_command(lib, Command(id=1, command="run_until", book="vol", arg=None, created_at=ts), None)
    assert lib.get_meta("run_until") == "vol"

    (tmp_path / "b.djvu").touch(); lib.add([tmp_path / "b.djvu"])
    lib.set_status("b", "done")
    apply_command(lib, Command(id=2, command="run_until", book="b", arg=None, created_at=ts), None)
    assert lib.get_meta("run_until") == "vol"      # not overwritten: done is not accepted
    assert any(e.level == "error" and "run_until" in e.message for e in lib.events())

    apply_command(lib, Command(id=3, command="run_until", book=None, arg=None, created_at=ts), None)
    assert lib.get_meta("run_until") == "vol"      # without a book: also refused
