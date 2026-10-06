# tests/test_library.py
from pathlib import Path

import pytest

from techbookocr.library import Library, expand_inputs


def test_add_files_and_order(tmp_path):
    lib = Library(tmp_path)
    a, b = tmp_path / "a.djvu", tmp_path / "b.pdf"
    a.touch(); b.touch()
    res = lib.add([a, b])
    assert res.added == ["a", "b"] and not res.skipped
    lib.set_priority("b", 5)  # set_priority is added in this same task
    assert lib.next_book().name == "b"


def test_duplicate_path_and_stem_rejected(tmp_path):
    lib = Library(tmp_path)
    (tmp_path / "x").mkdir(); (tmp_path / "y").mkdir()
    f1, f2 = tmp_path / "x" / "vol.djvu", tmp_path / "y" / "vol.djvu"
    f1.touch(); f2.touch()
    res = lib.add([f1, f1, f2])
    assert res.added == ["vol"]
    reasons = [r for _, r in res.skipped]
    assert any("уже в очереди" in r or "already" in r for r in reasons)
    assert any("имя" in r or "name" in r for r in reasons)


def test_expand_inputs_dir_recursive(tmp_path):
    (tmp_path / "sub").mkdir()
    ok = tmp_path / "sub" / "к.djvu"; ok.touch()
    bad = tmp_path / "note.txt"; bad.touch()
    files, skipped = expand_inputs([tmp_path])
    assert files == [ok]
    assert skipped[0][0] == bad and skipped[0][1]  # the reason is non-empty


def test_commands_lifecycle(tmp_path):
    lib = Library(tmp_path)
    cid = lib.push_command("pause")
    lib.push_command("priority", book="vol", arg="3")
    pending = lib.poll_commands()
    assert [c.command for c in pending] == ["pause", "priority"]
    lib.consume([cid])
    assert [c.command for c in lib.poll_commands()] == ["priority"]
    with pytest.raises(Exception):
        lib.push_command("explode")


def test_consume_stale_and_events(tmp_path):
    lib = Library(tmp_path)
    lib.push_command("stop")
    stale = lib.consume_stale()
    assert [c.command for c in stale] == ["stop"] and lib.poll_commands() == []
    lib.add_event("info", "daemon started")
    lib.add_event("error", "boom", book="vol")
    ev = lib.events()
    assert ev[0].message == "boom" and ev[0].book == "vol"


def test_heartbeat_and_alive(tmp_path):
    """heartbeat is "last seen"; liveness is checked only by flock on daemon.lock."""
    from techbookocr.daemon import DaemonLock

    lib = Library(tmp_path)
    assert not lib.daemon_alive()          # nobody holds the lock
    lib.set_meta("daemon_state", "stopped")
    lib.heartbeat()
    assert not lib.daemon_alive()          # meta "stopped" + a fresh heartbeat != alive
    lib.set_meta("daemon_state", "running")
    assert not lib.daemon_alive()          # meta "running" without a lock is dead too
    with DaemonLock(tmp_path):
        assert lib.daemon_alive()          # the lock is held -> alive (no heartbeat needed)
    assert not lib.daemon_alive()          # lock released -> dead


def test_scans_cache(tmp_path):
    lib = Library(tmp_path)
    assert lib.scans("a") is None and not lib.has_scans("a")
    lib.set_scans("a", 753)
    assert lib.scans("a") == 753 and lib.has_scans("a")
    lib.set_scans("b", None)                      # not counted: remember that we tried
    assert lib.scans("b") is None and lib.has_scans("b")
