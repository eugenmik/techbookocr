import pytest
from typer.testing import CliRunner

from techbookocr.cli import app


def test_eval_unknown_model_lists_available(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('[models.alpha]\nadapter="dots"\nimage="i"\nmodel="m"\n', encoding="utf-8")
    r = CliRunner().invoke(app, ["eval", "--models", "alpha,nope", "--config", str(cfg)])
    assert r.exit_code == 2
    assert "nope" in r.output and "alpha" in r.output


def test_parse_scans_ranges():
    from techbookocr.cli import _parse_scans

    assert _parse_scans("0,5,10-12") == [0, 5, 10, 11, 12] and _parse_scans(None) is None


def test_run_rejects_bad_options(tmp_path):
    book = tmp_path / "b.pdf"
    book.write_bytes(b"%PDF")
    r = CliRunner().invoke(app, ["run", str(book), "--mode", "slow"])
    assert r.exit_code == 2 and "mode" in r.output
    r = CliRunner().invoke(app, ["run", str(book), "--redo", "everything"])
    assert r.exit_code == 2
    r = CliRunner().invoke(app, ["run", str(tmp_path / "missing.djvu")])
    assert r.exit_code == 2 and "not found" in r.output


def test_run_missing_models_exits_2(tmp_path):
    book = tmp_path / "b.pdf"
    book.write_bytes(b"%PDF")
    r = CliRunner().invoke(app, ["run", str(book), "--config", str(tmp_path / "none.toml")])
    assert r.exit_code == 2


def test_parse_scans_rejects_reversed_range():
    import pytest
    import typer

    from techbookocr.cli import _parse_scans

    with pytest.raises(typer.BadParameter, match="reversed"):
        _parse_scans("12-10")


def test_run_unexpected_error_logged_and_reraised(tmp_path, monkeypatch):
    book = tmp_path / "b.pdf"
    book.write_bytes(b"%PDF")

    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr("techbookocr.pipeline.runner.run_book", boom)
    out = tmp_path / "out"
    r = CliRunner().invoke(app, ["run", str(book), "--out", str(out)])
    assert r.exit_code == 1 and isinstance(r.exception, RuntimeError)
    assert "RuntimeError: bug" in (out / "b" / "work" / "logs" / "run.log").read_text(encoding="utf-8")


def test_parse_scans_non_numeric():
    import pytest
    import typer

    from techbookocr.cli import _parse_scans

    for bad in ("a", "1-x", "1,,2"):
        with pytest.raises(typer.BadParameter):
            _parse_scans(bad)


def test_run_mode_defaults_to_pipeline_config(tmp_path, monkeypatch):
    """Without --mode, mode comes from [pipeline]; --mode overrides it."""
    book = tmp_path / "b.pdf"
    book.write_bytes(b"%PDF")
    cfg = tmp_path / "c.toml"
    cfg.write_text('[pipeline]\nmode = "fast"\n')
    seen = []
    monkeypatch.setattr("techbookocr.pipeline.runner.run_book",
                        lambda b, o, c, opts: seen.append(opts.mode) or (tmp_path / "out"))
    for args, want in (([], "fast"), (["--mode", "cascade"], "cascade")):
        CliRunner().invoke(app, ["run", str(book), "--out", str(tmp_path / "out"), "--config", str(cfg)] + args)
    assert seen == ["fast", "cascade"]


def test_add_and_status(tmp_path):
    (tmp_path / "книга.djvu").touch()
    r = CliRunner().invoke(app, ["add", str(tmp_path), "--out", str(tmp_path / "out"),
                                 "--config", str(tmp_path / "none.toml")])
    assert r.exit_code == 0 and "книга" in r.output
    r = CliRunner().invoke(app, ["status", "--out", str(tmp_path / "out")])
    assert r.exit_code == 0 and "queued: 1" in r.output


def test_add_records_scans(tmp_path):
    import pymupdf

    from techbookocr.library import Library

    pdf = tmp_path / "b.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    doc.save(pdf)
    lib_dir = tmp_path / "lib"
    r = CliRunner().invoke(app, ["add", str(pdf), "--out", str(lib_dir)])
    assert r.exit_code == 0, r.output
    with Library(lib_dir) as lib:
        assert lib.scans("b") == 2


def test_pause_requires_live_daemon(tmp_path):
    r = CliRunner().invoke(app, ["pause", "--out", str(tmp_path)])
    assert r.exit_code == 1


def test_skip_applies_directly_when_daemon_dead(tmp_path):
    (tmp_path / "v.djvu").touch()
    CliRunner().invoke(app, ["add", str(tmp_path / "v.djvu"), "--out", str(tmp_path)])
    r = CliRunner().invoke(app, ["skip", "v", "--out", str(tmp_path)])
    assert r.exit_code == 0
    from techbookocr.library import Library
    assert Library(tmp_path).book("v").status == "skipped"


@pytest.mark.parametrize("status", ["done", "processing"])
def test_dead_daemon_skip_rejected_is_not_silent(tmp_path, status):
    """Direct-apply refusal (skip not from queued): exit 1, status in the refusal, book untouched."""
    (tmp_path / "v.djvu").touch()
    CliRunner().invoke(app, ["add", str(tmp_path / "v.djvu"), "--out", str(tmp_path)])
    from techbookocr.library import Library
    with Library(tmp_path) as lib:
        lib.set_status("v", status)
    r = CliRunner().invoke(app, ["skip", "v", "--out", str(tmp_path)])
    assert r.exit_code == 1 and status in r.output
    assert Library(tmp_path).book("v").status == status


def test_dead_daemon_retry_failed_book_succeeds(tmp_path):
    """Direct-apply retry failed -> queued: exit 0, the book is in the queue."""
    (tmp_path / "v.djvu").touch()
    CliRunner().invoke(app, ["add", str(tmp_path / "v.djvu"), "--out", str(tmp_path)])
    from techbookocr.library import Library
    with Library(tmp_path) as lib:
        lib.set_status("v", "failed")
    r = CliRunner().invoke(app, ["retry", "v", "--out", str(tmp_path)])
    assert r.exit_code == 0
    assert Library(tmp_path).book("v").status == "queued"


def test_summarize_cli(tmp_path, monkeypatch):
    """summarize by book name: summary in meta.json, MOC and books-index.md."""
    from contextlib import contextmanager
    d = tmp_path / "Книга"
    d.mkdir()
    (d / "book.md").write_text("# Т\n\nтекст", encoding="utf-8")
    (d / "meta.json").write_text('{"title":"Книга","lang":["ru"],"pages":1}', encoding="utf-8")
    from techbookocr import summarize as smz
    @contextmanager
    def fake(cfg):
        yield lambda prompt: '{"description":"О книге","keywords":["литьё"]}'
    monkeypatch.setattr(smz, "make_summarizer", fake)
    r = CliRunner().invoke(app, ["summarize", "Книга", "--out", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert '"summary"' in (d / "meta.json").read_text(encoding="utf-8")
    assert (tmp_path / "books-index.md").exists()


def test_summarize_cli_all_idempotent(tmp_path, monkeypatch):
    """--all: a book without meta.json is skipped with an error, one with meta.json is summarized."""
    from contextlib import contextmanager
    (tmp_path / "пустая").mkdir()
    d = tmp_path / "Книга"
    d.mkdir()
    (d / "book.md").write_text("текст", encoding="utf-8")
    (d / "meta.json").write_text('{"title":"Книга"}', encoding="utf-8")
    from techbookocr import summarize as smz
    @contextmanager
    def fake(cfg):
        yield lambda prompt: '{"description":"О книге","keywords":[]}'
    monkeypatch.setattr(smz, "make_summarizer", fake)
    r = CliRunner().invoke(app, ["summarize", "--all", "--out", str(tmp_path)])
    assert "Книга" in r.output


def test_fixes_command_lists_and_toggles(tmp_path):
    d = tmp_path / "cantor"
    d.mkdir()
    (d / "book.md").write_text("<!-- page: 34 scan: 0046 -->\n\n<td>Specific load (t mm)</td>\n", encoding="utf-8")
    (d / "quality.md").write_text("## Misprint and print-defect fixes\n\n| Page | Was | Now |\n|---|---|---|\n"
                                  "| 0046 (p. 34) | Specific load (t/mm) | Specific load (t mm) |\n", encoding="utf-8")
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'[library]\ndir = "{tmp_path}"\n[pipeline]\nfix_reject_dictionary_words = false\n', encoding="utf-8")
    r = CliRunner().invoke(app, ["fixes", "cantor", "--config", str(cfg)])
    assert r.exit_code == 0, r.output
    assert "0046-1" in r.output and "Specific load (t/mm) → Specific load (t mm)" in r.output
    assert "changes operator" in r.output            # rules applied: the rule reverted the fix while building the journal
    r = CliRunner().invoke(app, ["fixes", "cantor", "--apply", "0046-1", "--config", str(cfg)])
    assert r.exit_code == 0 and "Specific load (t mm)" in (d / "book.md").read_text(encoding="utf-8")
    r = CliRunner().invoke(app, ["fixes", "cantor", "--revert", "nope", "--config", str(cfg)])
    assert r.exit_code == 1 and "nope" in r.output
    r = CliRunner().invoke(app, ["fixes", "missing", "--config", str(cfg)])
    assert r.exit_code == 2


def _fix_book(tmp_path, dictionary=False):
    d = tmp_path / "cantor"
    d.mkdir()
    (d / "book.md").write_text("<!-- page: 34 scan: 0046 -->\n\n<td>Specific load (t mm)</td> Каток — 2 шт.\n",
                               encoding="utf-8")
    (d / "quality.md").write_text("## Misprint and print-defect fixes\n\n| Page | Was | Now |\n|---|---|---|\n"
                                  "| 0046 (p. 34) | Specific load (t/mm) | Specific load (t mm) |\n"
                                  "| 0046 (p. 34) | Катак — 2 шт. | Каток — 2 шт. |\n", encoding="utf-8")
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'[library]\ndir = "{tmp_path}"\n[pipeline]\n'
                   f'fix_reject_dictionary_words = {"true" if dictionary else "false"}\n', encoding="utf-8")
    return d, cfg


@pytest.mark.parametrize("args", [["--revert", "0046-1", "--apply", "0046-2"],
                                  ["--revert", "0046-1", "--keep", "0046-1"],
                                  ["--revert", ""], ["--keep", ""]])
def test_fixes_command_rejects_conflicting_or_empty_ids(tmp_path, args):
    d, cfg = _fix_book(tmp_path)
    md = (d / "book.md").read_bytes()
    r = CliRunner().invoke(app, ["fixes", "cantor", *args, "--config", str(cfg)])
    assert r.exit_code == 2, r.output
    assert (d / "book.md").read_bytes() == md and not (d / "fixes.json").exists()


def test_fixes_command_revert_restores_printed_text(tmp_path):
    d, cfg = _fix_book(tmp_path)
    r = CliRunner().invoke(app, ["fixes", "cantor", "--revert", "0046-2", "--config", str(cfg)])
    assert r.exit_code == 0, r.output
    assert "Катак — 2 шт." in (d / "book.md").read_text(encoding="utf-8")
    assert "rejected by user" in r.output


def test_fixes_command_read_only_while_processing(tmp_path):
    from techbookocr.library import Library
    d, cfg = _fix_book(tmp_path)
    (tmp_path / "cantor.djvu").touch()
    with Library(tmp_path) as lib:
        lib.add([tmp_path / "cantor.djvu"])
        lib.set_status("cantor", "processing")
    md, q = (d / "book.md").read_bytes(), (d / "quality.md").read_bytes()
    r = CliRunner().invoke(app, ["fixes", "cantor", "--config", str(cfg)])
    assert r.exit_code == 0, r.output
    assert "read-only: book is processing" in r.output and "0046-1" in r.output
    assert not (d / "fixes.json").exists()
    assert (d / "book.md").read_bytes() == md and (d / "quality.md").read_bytes() == q
    r = CliRunner().invoke(app, ["fixes", "cantor", "--revert", "0046-2", "--config", str(cfg)])
    assert r.exit_code == 1 and "processing" in r.output
    assert (d / "book.md").read_bytes() == md and not (d / "fixes.json").exists()


def test_fixes_command_first_revert_builds_journal_with_dictionary(tmp_path, monkeypatch):
    """The first call on an older book is --revert: the journal is built with the dictionary, no "?" is lost."""
    class Sp:
        def known(self, w):
            return w.lower() in {"катак", "каток", "шт"}
    monkeypatch.setattr("techbookocr.pipeline.postproc.spell.load_speller", lambda langs, d, log=None: Sp())
    d, cfg = _fix_book(tmp_path, dictionary=True)
    r = CliRunner().invoke(app, ["fixes", "cantor", "--apply", "0046-1", "--config", str(cfg)])
    assert r.exit_code == 0, r.output
    from techbookocr.fixes.journal import read_journal
    assert read_journal(d / "fixes.json").get("0046-2").suggested is True
