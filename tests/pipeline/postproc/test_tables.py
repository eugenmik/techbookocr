from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.postproc.tables import merge_table_fragments, move_table_footnotes

T = ('<table><thead><tr><th>Марка</th><th>S</th></tr></thead><tbody><tr><td>СЧ20</td><td>0,1</td></tr></tbody>'
     '<tfoot><tr><td colspan="2">* Легирование серой.<br>** Легирование марганцем.</td></tr></tfoot></table>')


def test_tfoot_moves_to_footnote_items_after_table():
    items = [Item(1, "p", 0, "Text", "до"), Item(2, "p", 1, "Table", T), Item(3, "p", 2, "Text", "после")]
    n = move_table_footnotes(items)
    assert n == 2
    assert [it.category for it in items] == ["Text", "Table", "Footnote", "Footnote", "Text"]
    assert "<tfoot" not in items[1].text and "СЧ20" in items[1].text and "Марка" in items[1].text
    assert items[2].text == "* Легирование серой." and items[3].text == "** Легирование марганцем."
    assert len({it.id for it in items}) == 5 and items[2].page == "p"


def test_last_colspan_row_with_marker_moves_too():
    html = ('<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr>'
            '<tr><td colspan="2">¹ Примечание к таблице.</td></tr></table>')
    items = [Item(2, "p", 1, "Table", html)]
    assert move_table_footnotes(items) == 1
    assert items[1].text == "¹ Примечание к таблице." and items[0].text.count("<tr>") == 2


def test_colspan_row_without_marker_and_plain_tables_untouched():
    html = '<table><tr><td>a</td><td>b</td></tr><tr><td colspan="2">Итого по группе</td></tr></table>'
    items = [Item(2, "p", 1, "Table", html), Item(3, "p", 2, "Text", "x")]
    assert move_table_footnotes(items) == 0 and items[0].text == html and len(items) == 2


def test_table_made_only_of_footnote_row_is_kept():
    html = '<table><tr><td colspan="2">* только сноска</td></tr></table>'
    items = [Item(2, "p", 1, "Table", html)]
    assert move_table_footnotes(items) == 0 and items[0].text == html


def test_merge_fragments_same_columns():
    html = ('<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>'
            '<table><tr><td>c</td><td>d</td></tr></table>')
    items = [Item(1, "p", 0, "Table", html)]
    assert merge_table_fragments(items) == 1
    assert items[0].text.count("<table") == 1 and items[0].text.count("<tr>") == 3
    assert items[0].text.index("c") > items[0].text.index("1")


def test_merge_fragments_text_between_becomes_colspan_row():
    html = ('<table><tr><td>a</td><td>b</td></tr></table>Вески залитые<table><tr><td>c</td><td>d</td></tr></table>')
    items = [Item(1, "p", 0, "Table", html)]
    assert merge_table_fragments(items) == 1
    assert '<td colspan="2">Вески залитые</td>' in items[0].text and items[0].text.count("<table") == 1


def test_merge_fragments_different_columns_untouched():
    html = '<table><tr><td>a</td><td>b</td></tr></table><table><tr><td>c</td></tr></table>'
    items = [Item(1, "p", 0, "Table", html)]
    assert merge_table_fragments(items) == 0 and items[0].text == html


def test_promote_marker_text_to_footnote():
    from techbookocr.pipeline.postproc.tables import promote_footnotes
    items = [Item(1, "p", 0, "Table", "<table><tr><td>x *</td></tr></table>"),
             Item(4, "p", 1, "Text", "Обычный абзац. * Не сноска"),
             Item(2, "p", 2, "Text", "* Диаметр ячейки сита 16 мм."), Item(3, "p", 3, "Text", "** Масса."),
             Item(5, "p", 4, "Text", "¹ Частота выше.")]
    assert promote_footnotes(items) == 3
    assert [it.category for it in items] == ["Table", "Text", "Footnote", "Footnote", "Footnote"]


def test_promote_skips_long_text_and_pagestart_bullet():
    from techbookocr.pipeline.postproc.tables import promote_footnotes
    items = [Item(1, "p", 0, "Text", "* " + "слово " * 120), Item(2, "p", 1, "Text", "* Пункт списка"),
             Item(3, "p", 2, "Text", "Основной текст.")]
    assert promote_footnotes(items) == 0


def test_promote_footnote_between_tables_when_marker_is_referenced():
    from techbookocr.pipeline.postproc.tables import promote_footnotes
    items = [Item(1, "p", 0, "Table", "<table><tr><td>Производительность *, м³/ч</td><td>1 730 **</td></tr></table>"),
             Item(2, "p", 1, "Text", "* Диаметр ячейки сита 16 мм."), Item(3, "p", 2, "Text", "** Масса указана."),
             Item(4, "p", 3, "Section-header", "48. Сводная таблица"),
             Item(5, "p", 4, "Table", "<table><tr><td>x</td></tr></table>")]
    assert promote_footnotes(items) == 2
    assert [it.category for it in items] == ["Table", "Footnote", "Footnote", "Section-header", "Table"]


def test_unmarked_tfoot_row_stays_and_marked_row_joined_into_one_paragraph():
    html = ('<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr>'
            '<tfoot><tr><td>Итого</td><td>3</td></tr><tr><td>*</td><td>Примечание к строке</td></tr></tfoot></table>')
    items = [Item(1, "p", 0, "Table", html)]
    assert move_table_footnotes(items) == 1
    assert "Итого" in items[0].text and items[1].text == "* Примечание к строке"


def test_unmarked_last_colspan_row_stays():
    html = '<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr><tr><td colspan="2">Итого по цеху</td></tr></table>'
    items = [Item(1, "p", 0, "Table", html)]
    assert move_table_footnotes(items) == 0 and "Итого по цеху" in items[0].text


def test_tables_with_new_caption_between_are_not_merged():
    t1 = '<table><tr><td>Марка</td><td>C, %</td></tr></table>'
    t2 = '<table><tr><td>Марка</td><td>HB</td></tr></table>'
    for between in ("<p>Таблица 13. Свойства</p>", "Таблица 13. Свойства", "<p>Продолжение табл. 4</p>"):
        items = [Item(1, "p", 0, "Table", t1 + between + t2)]
        assert merge_table_fragments(items) == 0 and items[0].text.count("<table") == 2


def test_merge_with_paragraph_subheading_between():
    t1 = '<table><tr><td>a</td><td>b</td></tr></table>'
    t2 = '<table><tr><td>c</td><td>d</td></tr></table>'
    items = [Item(1, "p", 0, "Table", t1 + "<p>Вески залитые</p>" + t2)]
    assert merge_table_fragments(items) == 1
    assert items[0].text.count("<table") == 1 and '<td colspan="2">Вески залитые</td>' in items[0].text
    assert "<p>" not in items[0].text


def test_merge_keeps_img_placeholder_between_fragments():
    t1 = '<table><tr><td>a</td><td>b</td></tr></table>'
    t2 = '<table><tr><td>c</td><td>d</td></tr></table>'
    items = [Item(1, "p", 0, "Table", t1 + "<p>Подзаголовок <img></p>" + t2)]
    assert merge_table_fragments(items) == 1
    assert items[0].text.count("<img") == 1 and "Подзаголовок" in items[0].text
    items = [Item(1, "p", 0, "Table", t1 + "<img>" + t2)]
    assert merge_table_fragments(items) == 1 and items[0].text.count("<img") == 1


def test_emphasised_and_letter_spaced_captions_block_merge():
    t1 = '<table><tr><td>a</td><td>b</td></tr></table>'
    t2 = '<table><tr><td>c</td><td>d</td></tr></table>'
    for between in ("*Таблица IX.12*", "**Таблица 4**", "Т а б л и ц а 13", "<p>_Таблица 5_</p>"):
        items = [Item(1, "p", 0, "Table", t1 + between + t2)]
        assert merge_table_fragments(items) == 0, between
