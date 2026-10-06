import os
import sys

from typer.testing import CliRunner

from techbookocr.cli import app


def test_find_panel_order(tmp_path):
    from techbookocr.cli import find_panel

    exe = tmp_path / "techbookocr-tui"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert find_panel({"TECHBOOKOCR_TUI": str(exe)}, which=lambda c: None) == exe
    assert find_panel({}, which=lambda c: str(exe), repo=tmp_path / "norepo") == exe
    assert find_panel({}, which=lambda c: None, repo=tmp_path / "norepo") is None


def test_tui_execs_panel(tmp_path, monkeypatch):
    exe = tmp_path / "techbookocr-tui"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("TECHBOOKOCR_TUI", str(exe))
    calls = []
    monkeypatch.setattr(os, "execv", lambda path, argv: calls.append((path, argv)))
    r = CliRunner().invoke(app, ["tui", "--out", str(tmp_path), "--config", str(tmp_path / "c.toml")])
    assert r.exit_code == 0, r.output
    path, argv = calls[0]
    assert path == str(exe)
    assert argv[1:3] == ["--bridge-cmd", f"{sys.executable} -m techbookocr"]
    assert argv[3:] == ["--out", str(tmp_path), "--config", str((tmp_path / "c.toml").resolve())]


def test_tui_without_panel_explains_build(tmp_path, monkeypatch):
    monkeypatch.delenv("TECHBOOKOCR_TUI", raising=False)
    monkeypatch.setattr("techbookocr.cli.find_panel", lambda env, **kw: None)
    r = CliRunner().invoke(app, ["tui", "--out", str(tmp_path)])
    assert r.exit_code == 2
    assert "cd panel && bun install && bun run build" in r.output


def _exe(tmp_path, mode=0o755):
    exe = tmp_path / "techbookocr-tui"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(mode)
    return exe


def test_tui_bridge_cmd_roundtrips_with_spaces(tmp_path, monkeypatch):
    import shlex

    monkeypatch.setenv("TECHBOOKOCR_TUI", str(_exe(tmp_path)))
    monkeypatch.setattr(sys, "executable", "/home/me/my venv/bin/python")
    calls = []
    monkeypatch.setattr(os, "execv", lambda path, argv: calls.append(argv))
    r = CliRunner().invoke(app, ["tui"])
    assert r.exit_code == 0, r.output
    assert shlex.split(calls[0][2]) == ["/home/me/my venv/bin/python", "-m", "techbookocr"]


def test_tui_missing_env_binary_names_path(tmp_path, monkeypatch):
    missing = tmp_path / "nope"
    monkeypatch.setenv("TECHBOOKOCR_TUI", str(missing))
    r = CliRunner().invoke(app, ["tui"])
    assert r.exit_code == 2
    assert str(missing) in r.output


def test_tui_non_executable_env_binary(tmp_path, monkeypatch):
    f = _exe(tmp_path, 0o644)
    monkeypatch.setenv("TECHBOOKOCR_TUI", str(f))
    r = CliRunner().invoke(app, ["tui"])
    assert r.exit_code == 2
    assert str(f) in r.output


def test_tui_execv_oserror(tmp_path, monkeypatch):
    exe = _exe(tmp_path)
    monkeypatch.setenv("TECHBOOKOCR_TUI", str(exe))

    def boom(path, argv):
        raise OSError("Exec format error")

    monkeypatch.setattr(os, "execv", boom)
    r = CliRunner().invoke(app, ["tui"])
    assert r.exit_code == 2
    assert "Exec format error" in r.output and str(exe) in r.output
