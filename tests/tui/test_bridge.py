import json
import subprocess
import sys

import pytest

from techbookocr.library import Library


def _bridge(tmp_path, monkeypatch=None):
    from techbookocr.tui.bridge import Bridge

    (tmp_path / "a.djvu").touch()
    with Library(tmp_path) as lib:
        lib.add([tmp_path / "a.djvu"])
    toml = tmp_path / "b.toml"
    toml.write_text(f'[library]\ndir = "{tmp_path}"\n[pipeline]\nmode = "fast"  # режим\n', encoding="utf-8")
    if monkeypatch:
        monkeypatch.setattr("techbookocr.tui.data.gpu", lambda: None)
        monkeypatch.setattr("techbookocr.tui.snapshot.model_info", lambda: None)
    return Bridge(tmp_path, toml)


def test_handle_ops(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    r = b.handle({"id": 1, "op": "snapshot"})
    assert r["id"] == 1 and r["ok"] and r["data"]["books"][0]["name"] == "a"
    assert b.handle({"id": 2, "op": "book", "name": "a"})["data"]["info"]["name"] == "a"
    r = b.handle({"id": 3, "op": "book", "name": "nope"})
    assert r == {"id": 3, "ok": False, "error": "no book nope"}
    r = b.handle({"id": 4, "op": "act", "action": "skip", "books": ["a"]})
    assert r["data"]["messages"] == ["skip a → skipped"]
    r = b.handle({"id": 5, "op": "act", "action": "bump", "books": ["a"], "delta": 1})
    assert r["data"]["messages"] == ["a: priority 1"]
    assert b.handle({"id": 6, "op": "act", "action": "explode", "books": []})["ok"] is False
    assert b.handle({"id": 7, "op": "nope"}) == {"id": 7, "ok": False, "error": "unknown op nope"}


def test_handle_operation_error_is_reply(tmp_path, monkeypatch):
    import sqlite3

    b = _bridge(tmp_path, monkeypatch)

    def locked():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(b.lib, "books", locked)
    r = b.handle({"id": 1, "op": "snapshot"})
    assert r == {"id": 1, "ok": False, "error": "OperationalError: database is locked"}


def test_settings_get_set_and_library_switch(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    fields = b.handle({"id": 1, "op": "settings_get"})["data"]["fields"]
    assert any(f["key"] == "mode" and f["comment"].startswith("fast: ") for f in fields)
    new_root = tmp_path / "other"
    r = b.handle({"id": 2, "op": "settings_set", "updates": [
        {"section": "pipeline", "key": "mode", "value": "cascade"},
        {"section": "library", "key": "dir", "value": str(new_root)}]})
    assert r["ok"] and r["data"]["root"] == str(new_root.resolve())
    assert b.lib.root == new_root and b.cfg.pipeline.mode == "cascade"
    assert "# режим" in b.toml.read_text(encoding="utf-8")


def test_settings_set_invalid_restores_file(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    before = b.toml.read_text(encoding="utf-8")
    r = b.handle({"id": 1, "op": "settings_set",
                  "updates": [{"section": "pipeline", "key": "webp_quality", "value": 1000}]})
    assert r["ok"] is False and "webp_quality" in r["error"]
    assert b.toml.read_text(encoding="utf-8") == before


def test_add_and_log_tail(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    (tmp_path / "n.pdf").write_bytes(b"%PDF-junk")
    r = b.handle({"id": 1, "op": "add", "paths": [str(tmp_path / "n.pdf")]})
    assert r["data"]["added"] == ["n"]
    (tmp_path / "daemon.log").write_text("x\ny\n", encoding="utf-8")
    assert b.handle({"id": 2, "op": "log_tail", "lines": 1})["data"]["lines"] == ["y"]


def test_subprocess_protocol(tmp_path):
    (tmp_path / "a.djvu").touch()
    with Library(tmp_path) as lib:
        lib.add([tmp_path / "a.djvu"])
    proc = subprocess.Popen([sys.executable, "-m", "techbookocr", "bridge", "--out", str(tmp_path)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready = json.loads(proc.stdout.readline())
        assert ready["ready"] is True and ready["v"] == 1 and ready["root"] == str(tmp_path.resolve())
        for i, req in enumerate([{"op": "snapshot"}, {"op": "nope"}, {"op": "log_tail", "lines": 3}], 1):
            proc.stdin.write(json.dumps({"id": i, **req}) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            reply = json.loads(line)                        # every stdout line is protocol JSON
            assert reply["id"] == i
        proc.stdin.close()
        assert proc.wait(timeout=20) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_stray_print_goes_to_stderr(tmp_path, capfd, monkeypatch):
    import io

    from techbookocr.tui import bridge as br

    b = _bridge(tmp_path, monkeypatch)
    monkeypatch.setattr(br, "_OPS", {**br._OPS, "noisy": lambda self, req: print("noise") or {"x": 1}})
    out = io.StringIO()
    br.serve(b, io.StringIO('{"id": 1, "op": "noisy"}\n'), out)
    assert [json.loads(l) for l in out.getvalue().splitlines()][-1] == {"id": 1, "ok": True, "data": {"x": 1}}
    assert "noise" not in out.getvalue()


def test_settings_set_unusable_library_dir_keeps_bridge_alive(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    before = b.toml.read_text(encoding="utf-8")
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    r = b.handle({"id": 1, "op": "settings_set",
                  "updates": [{"section": "library", "key": "dir", "value": str(blocker / "sub")}]})
    assert r["ok"] is False and r["error"]
    assert b.toml.read_text(encoding="utf-8") == before
    assert b.handle({"id": 2, "op": "snapshot"})["ok"] is True


def test_settings_set_restores_file_on_any_error(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    before = b.toml.read_text(encoding="utf-8")

    def boom(path):
        raise RuntimeError("boom")
    monkeypatch.setattr("techbookocr.tui.bridge.load_config", boom)
    r = b.handle({"id": 1, "op": "settings_set",
                  "updates": [{"section": "pipeline", "key": "mode", "value": "cascade"}]})
    assert r["ok"] is False and "boom" in r["error"]
    assert b.toml.read_text(encoding="utf-8") == before


def test_settings_set_removes_new_file_on_failure(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    b.toml = tmp_path / "missing.toml"
    r = b.handle({"id": 1, "op": "settings_set",
                  "updates": [{"section": "pipeline", "key": "webp_quality", "value": 1000}]})
    assert r["ok"] is False
    assert not b.toml.exists()


def test_unserializable_data_is_error_reply(tmp_path, monkeypatch):
    import io

    from techbookocr.tui import bridge as br

    b = _bridge(tmp_path, monkeypatch)
    monkeypatch.setattr(br, "_OPS", {**br._OPS, "bad": lambda self, req: {"x": {1, 2}}})
    out = io.StringIO()
    br.serve(b, io.StringIO('{"id": 1, "op": "bad"}\n{"id": 2, "op": "snapshot"}\n'), out)
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert lines[0]["id"] == 1 and lines[0]["ok"] is False and "serializ" in lines[0]["error"].lower()
    assert lines[1]["id"] == 2 and lines[1]["ok"] is True


def test_invalid_config_emits_ready_false(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[pipeline]\nmode = "slow"\n', encoding="utf-8")
    p = subprocess.run([sys.executable, "-m", "techbookocr", "bridge", "--out", str(tmp_path), "--config", str(bad)],
                       input="", capture_output=True, text=True, timeout=30)
    assert p.returncode == 2
    first = json.loads(p.stdout.splitlines()[0])
    assert first["ready"] is False and first["v"] == 1 and "mode" in first["error"]


def test_settings_set_unrelated_update_keeps_explicit_root(tmp_path, monkeypatch):
    """The bridge is started with --out different from library.dir in the toml: saving a foreign field does not switch the library."""
    from techbookocr.tui.bridge import Bridge

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "lib"
    toml = tmp_path / "b.toml"
    toml.write_text("[pipeline]\nwebp_quality = 70\n", encoding="utf-8")
    b = Bridge(root, toml)
    r = b.handle({"id": 1, "op": "settings_set",
                  "updates": [{"section": "pipeline", "key": "webp_quality", "value": 60}]})
    assert r["ok"] and r["data"]["root"] == str(root.resolve())
    assert b.lib.root == root and not (tmp_path / "out").exists()
    r = b.handle({"id": 2, "op": "settings_get"})
    assert r["ok"] and r["data"]["root"] == str(root.resolve())
    assert not (tmp_path / "out").exists()


def test_settings_get_reloads_external_edit(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    b.toml.write_text(b.toml.read_text(encoding="utf-8").replace('"fast"', '"cascade"'), encoding="utf-8")
    fields = b.handle({"id": 1, "op": "settings_get"})["data"]["fields"]
    assert next(f for f in fields if f["key"] == "mode")["value"] == "cascade"
    assert b.cfg.pipeline.mode == "cascade"


def test_settings_get_external_library_dir_change_switches(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    other = tmp_path / "other"
    b.toml.write_text(f'[library]\ndir = "{other}"\n', encoding="utf-8")
    r = b.handle({"id": 1, "op": "settings_get"})
    assert r["ok"] and r["data"]["root"] == str(other.resolve()) and b.lib.root == other


def test_settings_get_broken_toml_is_error(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    b.toml.write_text("[pipeline\nmode = ", encoding="utf-8")
    r = b.handle({"id": 1, "op": "settings_get"})
    assert r["ok"] is False and r["error"]
    b.toml.write_text('[pipeline]\nmode = "bogus"\n', encoding="utf-8")
    assert b.handle({"id": 2, "op": "settings_get"})["ok"] is False


def _book_with_fix(tmp_path):
    d = tmp_path / "a"
    d.mkdir(exist_ok=True)
    (d / "book.md").write_text("<!-- page: 34 scan: 0046 -->\n\n<td>Specific load (t mm)</td>\n", encoding="utf-8")
    (d / "quality.md").write_text("## Misprint and print-defect fixes\n\n| Page | Was | Now |\n|---|---|---|\n"
                                  "| 0046 (p. 34) | Specific load (t/mm) | Specific load (t mm) |\n", encoding="utf-8")
    return d


def test_fixes_ops(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    monkeypatch.setattr("techbookocr.pipeline.postproc.spell.load_speller", lambda langs, d, log=None: None)
    d = _book_with_fix(tmp_path)
    assert b.handle({"id": 1, "op": "book", "name": "a"})["data"]["fixes"] == \
        {"total": 1, "suggested": None, "reviewed": False}
    r = b.handle({"id": 2, "op": "fixes", "book": "a"})["data"]
    assert r["editable"] is True and r["why_not"] is None
    assert r["fixes"][0]["state"] == "reverted" and r["counts"]["reverted"] == 1     # the rule reverted it
    r = b.handle({"id": 3, "op": "fix_set", "book": "a", "fix": "0046-1", "applied": True})
    assert r["ok"] and r["data"]["fix"]["state"] == "applied" and r["data"]["counts"]["applied"] == 1
    assert "Specific load (t mm)" in (d / "book.md").read_text(encoding="utf-8")
    r = b.handle({"id": 4, "op": "fix_keep", "book": "a", "fix": "0046-1"})
    assert r["ok"] and r["data"]["fix"]["decided_by"] == "user"
    r = b.handle({"id": 5, "op": "fix_set", "book": "a", "fix": "nope", "applied": False})
    assert r["ok"] is False and "nope" in r["error"]
    assert b.handle({"id": 6, "op": "fixes", "book": "zzz"})["ok"] is False


def test_fixes_reply_has_crop_and_out_dir(tmp_path, monkeypatch):
    """The fixes reply carries each fix's crop and the absolute book folder: the panel opens the crop on v."""
    from techbookocr.fixes.journal import Fix, Journal, save_journal
    b = _bridge(tmp_path, monkeypatch)
    d = _book_with_fix(tmp_path)
    save_journal(d / "fixes.json", Journal([Fix(
        id="0046-1", scan="0046", page="34", block=3, kind="table", was="Specific load (t/mm)",
        now="Specific load (t mm)", state="applied", before="<td>", after="</td>", crop="fixes/0046-b3.webp")]))
    r = b.handle({"id": 1, "op": "fixes", "book": "a"})["data"]
    assert r["fixes"][0]["crop"] == "fixes/0046-b3.webp"
    assert r["out_dir"] == str(d.resolve())


def test_fixes_read_only_while_processing(tmp_path, monkeypatch):
    b = _bridge(tmp_path, monkeypatch)
    monkeypatch.setattr("techbookocr.pipeline.postproc.spell.load_speller", lambda langs, d, log=None: None)
    d = _book_with_fix(tmp_path)
    b.lib.set_status("a", "processing")
    r = b.handle({"id": 1, "op": "fixes", "book": "a"})["data"]
    assert r["editable"] is False and r["why_not"] == "book is processing" and len(r["fixes"]) == 1
    assert not (d / "fixes.json").exists()                                  # read-only: no files are written
    r = b.handle({"id": 2, "op": "fix_set", "book": "a", "fix": "0046-1", "applied": False})
    assert r["ok"] is False and "processing" in r["error"]


def test_book_op_survives_unreadable_quality(tmp_path, monkeypatch):
    """A non-UTF-8 quality.md: the Book screen opens, the fix summary is null."""
    b = _bridge(tmp_path, monkeypatch)
    d = _book_with_fix(tmp_path)
    (d / "quality.md").write_bytes(b"## Misprint and print-defect fixes\n\xff\xfe bad\n")
    r = b.handle({"id": 1, "op": "book", "name": "a"})
    assert r["ok"], r
    assert r["data"]["fixes"] is None


def test_fix_set_first_call_builds_journal_with_dictionary(tmp_path, monkeypatch):
    """fix_set is the first to build an older book's journal, with the dictionary: the neighbouring fix keeps its "?"."""
    class Sp:
        def known(self, w):
            return w.lower() in {"катак", "каток", "шт"}
    b = _bridge(tmp_path, monkeypatch)
    monkeypatch.setattr("techbookocr.pipeline.postproc.spell.load_speller", lambda langs, d, log=None: Sp())
    d = _book_with_fix(tmp_path)
    (d / "book.md").write_text("<!-- page: 34 scan: 0046 -->\n\n<td>Specific load (t mm)</td> Каток — 2 шт.\n",
                               encoding="utf-8")
    with (d / "quality.md").open("a", encoding="utf-8") as fh:
        fh.write("| 0046 (p. 34) | Катак — 2 шт. | Каток — 2 шт. |\n")
    r = b.handle({"id": 1, "op": "fix_set", "book": "a", "fix": "0046-1", "applied": True})
    assert r["ok"], r
    assert r["data"]["counts"]["suggested"] == 1
    r = b.handle({"id": 2, "op": "fix_keep", "book": "a", "fix": "0046-2"})
    assert r["ok"] and r["data"]["fix"]["decided_by"] == "user" and r["data"]["counts"]["suggested"] == 0
