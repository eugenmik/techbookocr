from techbookocr.pipeline.guard import clean_b, guarded_b, sibling_index
from techbookocr.pipeline.state import BlockRow

A = "Сущность магнитных методов заключается в создании в детали равномерного магнитного поля, и равномер-"
TABLE_B = ("*Таблица IX.11*\n\n| Выявление дефектов при намагничивании |  |  |\n| :-- | :-- | :-- |\n"
           "| Режим для контроля | Н, Э | Размеры дефекта |\n| А | 60 | 2,5 |\n| Б | 30 | 10 |")
OTHERS = ["Таблица IX.11", "Выявление дефектов при намагничивании",
          "<table><tr><td>Режим для контроля</td><td>Н, Э</td><td>Размеры дефекта</td></tr>"
          "<tr><td>А</td><td>60</td><td>2,5</td></tr><tr><td>Б</td><td>30</td><td>10</td></tr></table>"]


def test_pipe_table_copy_of_other_blocks_is_stripped():
    assert clean_b(A + "\n\n" + TABLE_B, A, OTHERS) == A


def test_neighbour_line_stripped_own_line_kept():
    a = "** Масса указана без учета шкафов управления."
    b = "Диаметр ячейки сила 10 мм.\n* Масса указана без учета шкафов управления."
    assert clean_b(b, a, ["* Диаметр ячейки сита 16 мм."]) == "* Масса указана без учета шкафов управления."


def test_supported_by_a_is_kept_even_if_repeated_elsewhere():
    b = "Таблица IX.11 и текст"
    assert clean_b(b, "Таблица IX.11 и текст", ["Таблица IX.11"]) == b


def test_math_bars_are_not_a_table():
    b = "Сравниваем $ |D| $ с $ 2\\sqrt{L} $. Если $ |D| > 2 $, то так."
    assert clean_b(b, "Сравниваем $|D|$ с $2\\sqrt{L}$.", ["Пустой текст про другое"]) == b


def test_nothing_foreign_returns_unchanged_and_empty_becomes_none():
    assert clean_b("Обычный текст блока.", "Обычный текст блока.", []) == "Обычный текст блока."
    blk = BlockRow(id=1, page="p", ord=0, category="Text", kind="text", text_a="", text_b="Таблица IX.11",
                   drafts_status="done")
    sib = sibling_index([blk, BlockRow(id=2, page="p", ord=1, category="Caption", kind="caption",
                                       text_a="Таблица IX.11")])
    assert guarded_b(blk, sib) is None


def test_guarded_b_skips_tables_formulas_and_failed_drafts():
    blk = BlockRow(id=1, page="p", ord=0, category="Table", kind="table", text_a="<table></table>",
                   text_b="<table><tr><td>x</td></tr></table>", drafts_status="done")
    assert guarded_b(blk, sibling_index([blk])) == "<table><tr><td>x</td></tr></table>"
    failed = BlockRow(id=2, page="p", ord=1, category="Text", kind="text", text_b="x", drafts_status="failed")
    assert guarded_b(failed, sibling_index([failed])) is None
