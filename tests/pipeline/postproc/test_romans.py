from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.postproc.romans import fix_roman_refs, roman_chapter


def test_roman_chapter_mapping():
    assert [roman_chapter(x) for x in ("1", "11", "111", "1V", "V1", "V11", "1X", "X1", "VIII", "4", "12", "1A")] == [
        "I", "II", "III", "IV", "VI", "VII", "IX", "XI", None, None, None, None]


def _book():
    items = [Item(1, "a", 0, "Caption", "Рис. I.19. Структура"), Item(2, "a", 1, "Text", "см. табл. IV.15 и рис. VI.31, рис. IX.6."),
             Item(3, "b", 0, "Text", "как на рис. 1.27 (Рис. 1. 28) и в Таблица 11.32, табл. 1V.4."),
             Item(4, "b", 1, "Caption", "Таблица 1.34"), Item(5, "c", 0, "Text", "рис. 1.54, 5.2, 12.3 и 2,5")]
    return items, ["a", "b", "c"]


def test_fix_roman_refs_in_roman_book():
    items, order = _book()
    n = fix_roman_refs(items, order)
    assert items[2].text == "как на рис. I.27 (Рис. I. 28) и в Таблица II.32, табл. IV.4."
    assert items[3].text == "Таблица I.34" and items[0].text == "Рис. I.19. Структура"
    assert items[4].text == "рис. I.54, 5.2, 12.3 и 2,5"
    assert n == 6


def test_arabic_book_with_one_stray_roman_ref_untouched():
    items = [Item(i, f"p{i}", 0, "Text", f"см. рис. 1.{i} и табл. 11.{i + 1}") for i in range(10)]
    items[3].text = "см. рис. I.5"
    before = [it.text for it in items]
    assert fix_roman_refs(items, [f"p{i}" for i in range(10)]) == 0 and [it.text for it in items] == before


def test_roman_without_v_or_x_is_not_evidence():
    items = [Item(1, "a", 0, "Text", "рис. I.5, табл. II.3, рис. III.1"), Item(2, "a", 1, "Text", "рис. 1.7")]
    assert fix_roman_refs(items, ["a"]) == 0


def test_arabic_competition_blocks_rewrite():
    items = [Item(1, "a", 0, "Text", "рис. IV.3 рис. VI.1 рис. 3.2 рис. 4.3 рис. 5.1"), Item(2, "a", 1, "Text", "рис. 1.7")]
    assert fix_roman_refs(items, ["a"]) == 0


def test_false_positive_prefixes_and_three_part_numbers_untouched():
    items = [Item(1, "a", 0, "Text", "рис. IV.3 рис. VI.1 рис. IX.2 табл. V.1"),
             Item(2, "a", 1, "Text", "глубиной 1.5 м, глины 1.2 т, Рис. 1.2.1, Рисунок 1.5, рис. 11.2.3, главная 1.5")]
    fix_roman_refs(items, ["a"])
    assert items[1].text == ("глубиной 1.5 м, глины 1.2 т, Рис. 1.2.1, Рисунок I.5, рис. 11.2.3, главная 1.5")
