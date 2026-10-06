import pytest

from techbookocr.eval.metrics import score_page, split_markdown

GOLD = """<!-- page: 41 -->
## Методы количественного анализа фаз

Наиболее простым, но недостаточно точным методом количественного анализа является метод сравнения.

Объемная доля графита рассчитывается по формуле

$$
W_г = \\frac{n_{ср}}{N_{общ}} 100
$$

<table><tr><td>До 15</td><td>3</td></tr><tr><td>15—25</td><td>4</td></tr></table>

Для расчета массового количества графита необходимо учесть его плотность 2,2 г/см3.
"""


def test_split_markdown():
    p = split_markdown(GOLD)
    assert len(p.tables) == 1 and len(p.formulas) == 1
    assert "<table" not in p.text and "frac" not in p.text and "##" not in p.text and "page:" not in p.text
    assert p.text.startswith("Методы количественного")
    assert len(p.paragraphs) == 4


def test_perfect_page():
    s = score_page(GOLD, GOLD)
    assert s.cer == 0 and s.num_f1 == 1 and s.teds == 1 and s.formula_cer == 0 and s.order == 1


def test_number_error_detected():
    pred = GOLD.replace("2,2 г/см3", "2,7 г/см3")
    s = score_page(pred, GOLD)
    assert s.num_recall < 1 and s.cer > 0


def test_missing_table_and_formula():
    pred = "## Методы количественного анализа фаз\n\nНаиболее простым методом.\n"
    s = score_page(pred, GOLD)
    assert s.teds == 0 and s.formula_cer == 1.0


def test_swapped_paragraphs_reduce_order():
    a = "Первый длинный абзац о технологии литья чугуна в песчаные формы."
    b = "Второй длинный абзац о технологии плавки стали в индукционных печах."
    c = "Третий длинный абзац о контроле качества отливок и дефектах литья."
    gold = f"{a}\n\n{b}\n\n{c}\n"
    pred = f"{c}\n\n{b}\n\n{a}\n"
    assert score_page(pred, gold).order == pytest.approx(0.0)


def test_no_tables_gives_none():
    s = score_page("Текст", "Текст")
    assert s.teds is None and s.formula_cer is None


def test_numbers_ignore_markup():
    gold = "<!-- page: 41 -->\n\n![](img_001.png)\n\nТекст 5 мм.\n\n<table><tr><td rowspan='2'>7</td><td colspan='3'>8</td></tr></table>"
    pred = "<!-- page: 99 -->\n\n![](img_777.png)\n\nТекст 5 мм.\n\n<table><tr><td>7</td><td>8</td></tr></table>"
    assert score_page(pred, gold).num_f1 == 1.0


def test_identical_repeated_paragraphs_order_one():
    a = "Первый абзац достаточно длинный для сопоставления порядка чтения."
    md = f"{a}\n\nКороткий.\n\n{a}\n\nИ ещё один совсем другой абзац для проверки порядка чтения."
    assert score_page(md, md).order == 1.0


def test_pipe_table_equals_html_table():
    html = "<table><tr><td>d</td><td>H</td></tr><tr><td>3</td><td>40</td></tr></table>"
    pipe = "| d | H |\n|---|:--:|\n| 3 | 40 |"
    s = score_page(f"Текст перед таблицей.\n\n{pipe}\n\nТекст после.", f"Текст перед таблицей.\n\n{html}\n\nТекст после.")
    assert s.cer == 0 and s.teds == 1.0 and s.teds_struct == 1.0
    assert "|" not in split_markdown(pipe).text


def test_inequality_text_not_eaten():
    assert "t < 500 °C и s > 300 МПа" in split_markdown("t < 500 °C и s > 300 МПа").text


def test_exponent_and_thousands_numbers():
    s = score_page("г/см³ и 10⁻³, 1 350 000", "г/см3 и $10^{-3}$, 1350000")
    assert s.num_recall == 1.0 and s.num_f1 == 1.0


def test_footnote_markdown_reference_removed():
    """Footnote references [^1] should be stripped from text."""
    gold = "текст[^1] 5,2 [^2]\n\n[^1]: Примечание 3"
    s = score_page(gold, gold)
    assert s.num_f1 == 1.0
    # Number tokens should only be ['5,2', '3'], not include '1' or '2'
    from techbookocr.eval.metrics import _number_tokens
    tokens = _number_tokens(split_markdown(gold))
    assert sorted(tokens) == ['3', '5,2']


def test_footnote_asterisk_variant():
    """Asterisk variant of footnotes should extract the same numbers as markdown footnotes."""
    gold = "текст[^1] 5,2 [^2]\n\n[^1]: Примечание 3"
    pred = "текст* 5,2 **\n\n* Примечание 3"
    s = score_page(pred, gold)
    assert s.num_f1 == 1.0


def test_footnote_superscript_variant():
    """Superscript variant of footnotes should extract the same numbers as markdown footnotes."""
    gold = "текст[^1] 5,2 [^2]\n\n[^1]: Примечание 3"
    pred = "текст¹ 5,2\n\nПримечание 3"
    s = score_page(pred, gold)
    assert s.num_f1 == 1.0


def test_cubic_exponents_unaffected():
    """Cubic meter (m³, Cyrillic m) and power (10³) should not be stripped (superscript preserved)."""
    md = "объем м³ и 10³ в формуле"
    from techbookocr.eval.normalize import strip_note_markers
    cleaned = strip_note_markers(md)
    # Should preserve m3 (Cyrillic m) and 10³ (not strip the superscript 3)
    assert "м³" in cleaned
    assert "10³" in cleaned


def test_bullet_list_unaffected():
    """Bullet lists (* a\n* b) should remain as text and preserve exact structure."""
    from techbookocr.eval.normalize import strip_note_markers

    # Test consecutive list
    md1 = "* первый пункт\n* второй пункт"
    result1 = strip_note_markers(md1)
    assert result1 == md1, f"Consecutive list should be unchanged: {repr(result1)}"

    # Test list with gap
    md2 = "* первый пункт\n\n* второй пункт"
    result2 = strip_note_markers(md2)
    assert result2 == md2, f"List with gap should be unchanged: {repr(result2)}"

    # Test standalone note marker (should be stripped)
    md3 = "* Примечание 3"
    result3 = strip_note_markers(md3)
    assert result3 == "Примечание 3", f"Standalone note should be stripped: {repr(result3)}"

    # Test escaped asterisk (should be stripped)
    md4 = "\\* Примечание"
    result4 = strip_note_markers(md4)
    assert result4 == "Примечание", f"Escaped asterisk note should be stripped: {repr(result4)}"

    # Test through split_markdown to verify lists remain intact in parsed output
    p = split_markdown(md1)
    assert "первый пункт" in p.text
    assert "второй пункт" in p.text


def test_emphasis_markers_not_eaten():
    """Emphasis markers (**text**, *text*) should be removed as content, not eaten."""
    s = score_page("**жирный** текст и *курсив* слово", "жирный текст и курсив слово")
    assert s.cer == 0 and s.wer == 0, f"Emphasis should not affect scoring: cer={s.cer}, wer={s.wer}"


def test_numbered_heading_is_treated_the_same_on_both_sides():
    from techbookocr.eval.metrics import split_markdown
    gold = split_markdown("5. Составные части сит\n\nТекст.\n")
    pred = split_markdown("## 5. Составные части сит\n\nТекст.\n")
    assert gold.paragraphs == pred.paragraphs
    assert gold.text == pred.text
