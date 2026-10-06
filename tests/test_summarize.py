import json

import pytest

from techbookocr.config import Config, ConfigError
from techbookocr.summarize import (books_index_text, build_prompt, collect_signals,
                               parse_summary, run_summarize, summarize_book,
                               update_books_index)

BOOK_MD = """---
title: "Книга А"
lang: [ru]
type: book-source
---

<!-- page: 1 scan: 0001 -->

# Введение

Текст про пористость и пригары.

<!-- page: 5 scan: 0005 -->

## Глава 1. Дефекты

Ещё текст.
"""


def book_dir(root, name="Книга А", meta_extra=None, md=BOOK_MD):
    d = root / name
    d.mkdir(parents=True)
    (d / "book.md").write_text(md, encoding="utf-8")
    meta = {"title": name, "lang": ["ru"], "pages": 2, **(meta_extra or {})}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return d


def test_parse_summary_json():
    s = parse_summary('{"description": "Атлас дефектов.", "keywords": ["пористость", "трещины"]}')
    assert s == {"description": "Атлас дефектов.", "keywords": ["пористость", "трещины"],
                 "parsed": True}


def test_parse_summary_embedded_json():
    s = parse_summary('Вот ответ:\n```json\n{"description": "Про литьё", "keywords": []}\n```')
    assert s["description"] == "Про литьё" and s["parsed"]


def test_parse_summary_plain_text_fallback():
    """A broken/non-JSON reply does not crash: the whole text goes to description, keywords are empty."""
    s = parse_summary("Атлас дефектов отливок, рассмотрены раковины.")
    assert s["parsed"] is False and s["keywords"] == []
    assert s["description"].startswith("Атлас")


def test_collect_signals(tmp_path):
    sig = collect_signals(book_dir(tmp_path))
    assert sig["title"] == "Книга А" and sig["lang"] == "ru" and sig["pages"] == 2
    assert sig["headings"] == ["Введение", "Глава 1. Дефекты"]
    assert "type: book-source" not in sig["excerpt"]  # frontmatter is stripped
    assert sig["excerpt"].startswith("<!-- page: 1")


def test_build_prompt(tmp_path):
    p = build_prompt(collect_signals(book_dir(tmp_path)))
    assert "Книга А" in p and "Глава 1. Дефекты" in p and "JSON" in p


def test_summarize_book_writes_meta_and_moc(tmp_path):
    d = book_dir(tmp_path)
    prompts = []
    s = summarize_book(d, lambda p: prompts.append(p)
                       or '{"description":"О дефектах отливок.","keywords":["пористость"]}')
    assert s["parsed"] and len(prompts) == 1
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["summary"]["description"] == "О дефектах отливок."
    assert meta["summary"]["keywords"] == ["пористость"]
    moc = (d / "Книга А.md").read_text(encoding="utf-8")
    assert 'description: "О дефектах отливок."' in moc
    assert "О дефектах отливок.\n\n## Contents" in moc  # visible preview paragraph
    assert "Текст про пористость" in (d / "book.md").read_text(encoding="utf-8")  # book.md is untouched


def test_summarize_book_collision_name(tmp_path):
    """A book named book: the MOC goes to the Russian-suffixed TOC file, book.md is not overwritten."""
    d = book_dir(tmp_path, name="book")
    summarize_book(d, lambda p: '{"description":"x","keywords":[]}')
    assert (d / "book-contents.md").exists()
    assert "Текст про пористость" in (d / "book.md").read_text(encoding="utf-8")


def test_run_summarize_idempotent(tmp_path):
    """A summary already exists and no redo: the model is not called, returns None."""
    d = book_dir(tmp_path, meta_extra={"summary": {"description": "есть", "keywords": []}})
    calls = []
    assert run_summarize(tmp_path, d.name, Config(), call=lambda p: calls.append(p)) is None
    assert calls == []


def test_run_summarize_redo(tmp_path):
    d = book_dir(tmp_path, meta_extra={"summary": {"description": "старое", "keywords": []}})
    s = run_summarize(tmp_path, d.name, Config(), redo=True,
                      call=lambda p: '{"description":"новое","keywords":[]}')
    assert s["description"] == "новое"
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["summary"]["description"] == "новое"


def test_run_summarize_missing_meta(tmp_path):
    (tmp_path / "нет").mkdir()
    with pytest.raises(ConfigError):
        run_summarize(tmp_path, "нет", Config(), call=lambda p: "{}")


def test_books_index(tmp_path):
    book_dir(tmp_path, "А Атлас", {"summary": {"description": "О дефектах", "keywords": []}})
    book_dir(tmp_path, "Б Справочник")
    idx = books_index_text(tmp_path)
    assert "[[А Атлас|А Атлас]] — О дефектах" in idx
    assert "[[Б Справочник|Б Справочник]] — —" in idx  # without a summary: a dash


def test_update_books_index_writes_file(tmp_path):
    book_dir(tmp_path)
    p = update_books_index(tmp_path)
    assert p.name == "books-index.md" and "[[Книга А|Книга А]]" in p.read_text(encoding="utf-8")
