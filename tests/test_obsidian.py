import pytest

from techbookocr.models.types import Block
from techbookocr.obsidian import frontmatter, moc_note, slugify, toc

META = {"title": "Атлас литейных дефектов", "author": "Воронин", "year": 2005,
        "lang": ["ru"], "pages": 327}


def test_frontmatter():
    fm = frontmatter(META)
    assert fm.startswith("---\n") and fm.endswith("---\n\n")
    assert 'title: "Атлас литейных дефектов"' in fm
    assert "author: Воронин" in fm and "year: 2005" in fm
    assert "lang: [ru]" in fm and "pages: 327" in fm
    assert "tags: []" in fm and "type: book-source" in fm
    # empty author/year: a key without a value, not "None"
    fm2 = frontmatter({**META, "author": None, "year": None})
    assert "author:\n" in fm2 and "year:\n" in fm2 and "None" not in fm2


def test_slugify():
    assert slugify("Глава 3. Пористость (газовая)") == "глава-3-пористость-газовая"
    assert slugify("IV.  Усадочные раковины!") == "iv-усадочные-раковины"
    assert slugify("C% SiO2/Al2O3") == "c-sio2al2o3"


def test_toc():
    md = ("<!-- page: 3 scan: 0002 -->\n\n# Введение\n\nтекст\n\n"
          "<!-- page: 10 scan: 0009 -->\n\n## 1.1 Газовые раковины\n\n"
          "### под-заголовок\n\n```\n# не заголовок\n```\n\n"
          "<!-- page: ? scan: 0010 -->\n\n## 1.2 Шлаковые\n")
    t = toc(md)
    assert [(e.level, e.title, e.printed) for e in t] == [
        (1, "Введение", "3"), (2, "1.1 Газовые раковины", "10"), (2, "1.2 Шлаковые", None)]
    assert [e.slug for e in t] == ["введение", "11-газовые-раковины", "12-шлаковые"]


def test_toc_empty_and_duplicates():
    assert toc("нет заголовков") == []
    t = toc("# Одно\n\n# Одно\n")
    assert [e.slug for e in t] == ["одно", "одно"]  # duplicates are a format limitation, not a crash


def test_frontmatter_with_summary():
    meta = {**META, "summary": {"description": 'Атлас "чёрных" дефектов',
                                "keywords": ["пористость", "трещины"]}}
    fm = frontmatter(meta)
    assert 'description: "Атлас \\"чёрных\\" дефектов"' in fm
    assert 'keywords: ["пористость", "трещины"]' in fm


def test_moc_note_summary_paragraph():
    md = "<!-- page: 5 scan: 0004 -->\n\n# Глава\n"
    meta = {**META, "summary": {"description": "Краткое превью.", "keywords": []}}
    note = moc_note("Книга", meta, md)
    assert "Краткое превью.\n\n## Contents" in note
    assert "Краткое превью." not in moc_note("Книга", META, md)  # without a summary: as before


def test_moc_name_helper():
    from techbookocr.obsidian import moc_name
    assert moc_name("book") == "book-contents" and moc_name("quality") == "quality-contents"
    assert moc_name("Книга") == "Книга"


def test_moc_note():
    md = "<!-- page: 5 scan: 0004 -->\n\n# Глава [A] первая\n"
    note = moc_note("Книга Имя", META, md)
    assert note.startswith("---\n") and "## Contents" in note
    assert "[Book](book.md)" in note and "[Quality report](quality.md)" in note
    assert "[Глава \\[A\\] первая](book.md#глава-a-первая) — p. 5" in note


def test_finish_book_writes_frontmatter_and_moc(tmp_path):
    # integration via finish_book on a live state (pattern from tests/eval/test_cascade.py)
    from techbookocr.pipeline.runner import finish_book
    from techbookocr.pipeline.state import BookState, PageEntry

    work = tmp_path / "w"
    work.mkdir()
    with BookState(work / "state.sqlite") as st:
        st.add_pages([PageEntry(name="0000L", idx=0, scan=0, side="L", file="pages/0000L.png",
                                width=10, height=10)])
        st.set_layout("0000L", [Block("Text", "Текст страницы.", (1, 1, 9, 9))], status="done")
        st.mark_done("layout")
        finish_book(st, tmp_path, book_name="Книга Тест", source="x.djvu", lang="ru",
                    mode="fast", models={}, speller=None)
    md = (tmp_path / "book.md").read_text(encoding="utf-8")
    assert md.startswith("---\n") and "type: book-source" in md
    assert (tmp_path / "Книга Тест.md").exists()
    assert "[Book](book.md)" in (tmp_path / "Книга Тест.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("book_name", ["book", "quality"])
def test_finish_book_moc_name_collision(tmp_path, book_name):
    """A book name that matches a service file (book.md/quality.md): the MOC goes to <name>-toc.md (Russian TOC suffix)."""
    from techbookocr.pipeline.runner import finish_book
    from techbookocr.pipeline.state import BookState, PageEntry

    work = tmp_path / "w"
    work.mkdir()
    with BookState(work / "state.sqlite") as st:
        st.add_pages([PageEntry(name="0000L", idx=0, scan=0, side="L", file="pages/0000L.png",
                                width=10, height=10)])
        st.set_layout("0000L", [Block("Text", "Текст страницы.", (1, 1, 9, 9))], status="done")
        st.mark_done("layout")
        finish_book(st, tmp_path, book_name=book_name, source="x.djvu", lang="ru",
                    mode="fast", models={}, speller=None)
    body = (tmp_path / "book.md").read_text(encoding="utf-8")
    moc = (tmp_path / f"{book_name}-contents.md").read_text(encoding="utf-8")
    assert "Текст страницы" in body                    # book.md content is not overwritten by the MOC note
    assert "## Contents" in moc and moc != body      # the MOC is a separate file
    assert "## Contents" not in (tmp_path / "quality.md").read_text(encoding="utf-8")
