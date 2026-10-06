from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.postproc.stitch import mark_continuations, stitch_pages

ORDER = ["0001", "0002", "0003", "0004"]


def test_stitch_lowercase_continuation_with_hyphen():
    items = [Item(1, "0001", 0, "Text", "Структура ме-"), Item(2, "0001", 1, "Footnote", "* Сноска."),
             Item(3, "0002", 0, "Text", "талла зависит от скорости охлаждения.")]
    assert stitch_pages(items, ORDER, lambda w: w == "металла") == 1
    assert items[0].text == "Структура" and items[2].text == "металла зависит от скорости охлаждения."
    assert items[2].join_to == 1


def test_no_stitch_after_sentence_end_capital_gap_or_table():
    items = [Item(1, "0001", 0, "Text", "Конец абзаца."), Item(2, "0002", 0, "Text", "продолжение?"),
             Item(3, "0002", 1, "Text", "Абзац без точки"), Item(4, "0003", 0, "Text", "Новый абзац")]
    assert stitch_pages(items, ORDER, lambda w: True) == 0
    gap = [Item(1, "0001", 0, "Text", "текст без точки"), Item(2, "0003", 0, "Text", "продолжение")]
    assert stitch_pages(gap, ORDER, lambda w: True) == 0
    table_first = [Item(1, "0001", 0, "Text", "текст без точки"), Item(2, "0002", 0, "Table", "<table></table>")]
    assert stitch_pages(table_first, ORDER, lambda w: True) == 0


def test_table_continuation_note():
    items = [Item(1, "0002", 0, "Caption", "Продолжение табл. IV. 15"), Item(2, "0002", 1, "Table", "<table></table>"),
             Item(3, "0003", 0, "Caption", "Окончание таблицы 7"), Item(4, "0004", 0, "Table", "<table></table>")]
    assert mark_continuations(items) == 1
    assert items[1].note == "continues: table IV.15" and items[3].note is None


def test_sentence_end_with_closing_quote_and_lowercase_start():
    """Sentence ending with .» (period + closing quote) should not stitch with lowercase start."""
    items = [Item(1, "0001", 0, "Text", "Он сказал: «текст.»"), Item(2, "0002", 0, "Text", "продолжение")]
    assert stitch_pages(items, ORDER, lambda w: True) == 0
    assert items[0].text == "Он сказал: «текст.»" and items[1].text == "продолжение"


def test_no_stitch_on_list_marker():
    """Never stitch when next page starts with lowercase list marker (e.g., "a)" in Cyrillic)."""
    items = [Item(1, "0001", 0, "Text", "Список:"), Item(2, "0002", 0, "Text", "а) первый пункт")]
    assert stitch_pages(items, ORDER, lambda w: True) == 0
    assert items[0].text == "Список:" and items[1].text == "а) первый пункт"


def test_drop_empty_item_after_hyphen_join():
    """If previous item becomes empty after hyphen join, drop it."""
    items = [Item(1, "0001", 0, "Text", "ме-"), Item(2, "0001", 1, "Footnote", "* Сноска."),
             Item(3, "0002", 0, "Text", "талла")]
    n_before = len(items)
    stitch_pages(items, ORDER, lambda w: w == "металла")
    # The item with id=1 should be removed since it becomes empty
    assert len(items) == n_before - 1
    assert all(it.id != 1 for it in items)
