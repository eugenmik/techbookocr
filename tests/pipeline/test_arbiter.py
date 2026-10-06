import pytest

from techbookocr.config import PipelineConfig
from techbookocr.models.errors import TransportError
from techbookocr.models.types import Block, BlockResult
from techbookocr.pipeline.arbiter import (arbiter_max_tokens, build_prompt, fallback, judge, parse_answer, parse_answer_full,
                                      run_arbiter)
from techbookocr.pipeline.transport import StageAborted, TransportGuard
from tests.pipeline.fakes import NO_SLEEP, FakeVLM, new_state

CFG = PipelineConfig()
PARA = "Отливки из серого чугуна марки СЧ20 охлаждают в форме до температуры 400 °C, затем выбивают."


def test_prompt_contents():
    p = build_prompt("table", "ru", ["<table>A</table>", "<table>B</table>"])
    assert "Russian" in p and "one table block" in p
    assert "Draft A:\n<<<\n<table>A</table>\n>>>" in p and "Draft B:" in p
    assert "Never translate" in p and "«Таблица» stays «Таблица»" in p and "W_{г}" in p
    assert "rowspan/colspan" in p and p.rstrip().endswith("(use FIXES: [] if there were no misprints).")
    one = build_prompt("formula", "de", ["x^2"])
    assert "German" in one and "One OCR draft" in one and "Draft B" not in one and "LaTeX only" in one
    blind = build_prompt("text", "ru", [PARA, PARA], with_image=False)
    assert "image" not in blind.lower()


def test_parse_answer():
    text, fixes = parse_answer('Текст блока\nFIXES: [{"was": "обоим", "now": "обеими"}]', "text")
    assert text == "Текст блока" and fixes == [{"was": "обоим", "now": "обеими"}]
    assert parse_answer("```markdown\nТекст\n```\nFIXES: []", "text") == ("Текст", [])
    assert parse_answer("Текст\nFIXES: [oops", "text") == ("Текст", [])
    assert parse_answer_full("Текст\nFIXES: [oops", "text")[2] == "fixes unparsable"
    assert parse_answer("FIXES: []\nТекст\nещё", "text") == ("Текст\nещё", [])
    assert parse_answer("Вот:\n```\nТекст\nFIXES: []\n```", "text") == ("Текст", [])
    assert parse_answer("Здесь:\n```md\nТекст\n```\nпояснение", "text") == ("Текст", [])
    assert parse_answer("Текст\n```", "text") == ("Текст", [])
    multi = "Текст\nFIXES: [\n {'was': 'а', 'now': 'б'},\n]"
    assert parse_answer(multi, "text") == ("Текст", [{"was": "а", "now": "б"}])
    assert parse_answer("Here is the text:\nТекст", "text", [PARA])[0] == "Текст"
    assert parse_answer("Дано:\nТекст", "text", ["Дано:\nТекст"])[0] == "Дано:\nТекст"
    assert parse_answer("Текст без строки исправлений", "text") == ("Текст без строки исправлений", [])
    t, _ = parse_answer("Вот таблица:\n<table><tr><td>1</td></tr></table>\nFIXES: []", "table")
    assert t == "<table><tr><td>1</td></tr></table>"
    with pytest.raises(ValueError, match="no <table>"):
        parse_answer("таблицы нет", "table")


def test_judge_accepts_close_answer():
    fixed = PARA.replace("400", "450")
    v = judge("text", PARA, PARA.replace("СЧ20", "СЧ2О"), fixed, None, 0.15)
    assert v.status == "done" and v.source == "arbiter" and v.final == fixed and v.cer < 0.15


def test_judge_rejects_hallucination():
    v = judge("text", PARA, PARA, PARA + " Кроме того, отливки отжигают при 900 °C в течение двух часов.", None, 0.15)
    assert v.status == "rejected" and v.final == PARA and v.source == "fallback_a" and v.cer > 0.15


def test_judge_rejects_translation():
    a = "Таблица IV.16. Размеры весок (подъемов) стержней, мм"
    v = judge("caption", a, a, "Table IV.16. Dimensions of core hangers, mm", None, 0.15)
    assert v.status == "rejected" and v.final == a
    # even with a lenient CER threshold, a script change is caught separately
    v = judge("text", PARA, PARA, "Otlivki iz serogo chuguna marki SCh20 okhlazhdayut v forme do 400 C.", None, 1.0)
    assert v.status == "rejected" and "script" in v.note


@pytest.mark.parametrize("a,b,ans,kind", [
    ("W_g", "W_r", "W_{г}", "formula"),
    ("n_{g}=5", "n_{r}=5", "n_{г}=5", "formula"),
    ("Рис. 1.28. Схема", "Рис. 1.28. Схема", "Рис. I.28. Схема", "caption"),
    ("Рис. II.3", "Рис. II.3", "Рис. II.3", "caption"),
])
def test_judge_accepts(a, b, ans, kind):
    assert judge(kind, a, b, ans, None, 0.15).status == "done"


@pytest.mark.parametrize("ans,kind", [
    ("Table IV.16. Размеры весок", "caption"),
    ("<table><tr><td>Table 12</td></tr></table>", "table"),
    ("Here is the corrected text:\nОтливки из серого чугуна", "text"),
])
def test_judge_rejects_script(ans, kind):
    a = ("<table><tr><td>Таблица 12</td></tr></table>" if kind == "table"
         else "Таблица IV.16. Размеры весок" if kind == "caption" else "Отливки из серого чугуна")
    v = judge(kind, a, a, ans, None, 5.0)
    assert v.status == "rejected" and v.note.startswith("script changed")


def test_judge_rejects_long_rewrite_and_no_drafts_script():
    long = PARA * 3
    assert judge("text", long, long, PARA[::-1] * 3, None, 0.15).status == "rejected"
    v = judge("text", "", None, "По ГОСТ 1412 и DIN 1691 Здесь", None, 0.15)
    assert v.status == "done" and v.final.startswith("По ГОСТ") and "unverified: no drafts" in v.note
    assert "DIN" in v.note


def test_judge_keeps_answer_when_fallback_empty():
    v = judge("text", "", "", "Новый текст страницы", None, 0.15)
    assert v.final == "Новый текст страницы" and v.status == "done"


def test_parse_heading_and_empty_fixes():
    assert parse_answer("Примечания:\nТекст", "text", ["Примечаиия:\nТекст"])[0] == "Примечания:\nТекст"
    assert parse_answer("Литература:\nТекст", "text")[0] == "Литература:\nТекст"
    assert parse_answer("Here is it:\nТекст", "text", ["Текст"])[0] == "Текст"
    t, f = parse_answer("FIXES:\nАбзац см. [1] и далее", "text")
    assert t == "Абзац см. [1] и далее" and f == []


def test_judge_falls_back_to_b_when_a_loops():
    v = judge("text", "ab" * 400, PARA, None, "looping", 0.15)
    assert v.status == "failed" and v.final == PARA and v.source == "fallback_b" and v.note == "looping"
    assert fallback("", None) == ("", "fallback_a")


def test_max_tokens_follows_draft_length():
    assert arbiter_max_tokens(["x" * 100]) == 712 and arbiter_max_tokens(["x" * 10000]) == 8192
    assert arbiter_max_tokens([]) == 8192


def _disputed(st, names):
    for name in names:
        st.set_layout(name, [Block("Text", PARA, (100, 100, 900, 120))], status="done")
        blk = st.blocks(name)[0]
        st.update_block(blk.id, text_b=PARA.replace("СЧ20", "СЧ2О"), drafts_status="done", decision="arbiter",
                        consensus_status="done", arbiter_status="pending")


def test_run_arbiter_records_fixes(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    _disputed(st, ["0001"])
    reply = PARA + ('\nFIXES: [{"was": "охлаждают", "now": "затем"}, {"was": "СЧ2О", "now": "СЧ20"}, '
                    '{"was": "нет", "now": "отсутствует"}, {"was": "затем", "now": "затем"}, {"was": "...", "now": "..."}]')
    vlm = FakeVLM(lambda prompt: BlockResult(reply, raw=reply, seconds=3.0))
    assert run_arbiter(st, vlm, tmp_path / "work", CFG, "ru", TransportGuard(sleep=NO_SLEEP)) == 1
    b = st.blocks("0001")[0]
    assert (b.arbiter_status, b.final, b.final_source) == ("done", PARA, "arbiter")
    assert b.fixes == [{"was": "охлаждают", "now": "затем"}] and len(b.arbiter_fixes) == 5
    assert b.arbiter_seconds == 3.0 and b.arbiter_cer == 0.0 and b.arbiter_raw == reply
    _, prompt, max_tokens = vlm.calls[0]
    assert "Draft A" in prompt and "Draft B" in prompt and max_tokens == 512 + 2 * len(PARA)
    st.close()


def test_run_arbiter_looping_and_rejection_fall_back(tmp_path):
    st = new_state(tmp_path, names=("0001", "0002"))
    _disputed(st, ["0001", "0002"])
    replies = iter([BlockResult("ab" * 400, error="looping"), BlockResult("Совсем другой текст про сталь")])
    run_arbiter(st, FakeVLM(lambda p: next(replies)), tmp_path / "work", CFG, "ru", TransportGuard(sleep=NO_SLEEP))
    b1, b2 = st.blocks("0001")[0], st.blocks("0002")[0]
    assert (b1.arbiter_status, b1.final, b1.final_source, b1.arbiter_error) == ("failed", PARA, "fallback_a", "looping")
    assert (b2.arbiter_status, b2.final, b2.final_source) == ("rejected", PARA, "fallback_a")
    assert b2.arbiter_note.startswith("cer") and b2.arbiter_text == "Совсем другой текст про сталь"
    st.close()


def test_run_arbiter_transport_streak(tmp_path):
    names = ("0001", "0002", "0003", "0004")
    st = new_state(tmp_path, names=names)
    _disputed(st, names)
    with pytest.raises(StageAborted):
        run_arbiter(st, FakeVLM(lambda p: TransportError("down")), tmp_path / "work", CFG, "ru",
                    TransportGuard(retries=0, sleep=NO_SLEEP))
    b = st.blocks("0001")[0]
    assert b.arbiter_status == "pending" and b.final is None and b.arbiter_error.startswith("transport")
    assert st.pending("arbiter") == 4
    st.close()


def test_judge_rejects_mixed_script_word_not_in_drafts():
    """Voronin, p. 240: the arbiter returned a Cyrillic+Latin mixed-script word that is not in the drafts."""
    a = "<table><tr><td>Стержень прошпилена</td></tr></table>"
    v = judge("table", a, None, "<table><tr><td>Стержень прошпиlena</td></tr></table>", None, 5.0)
    assert v.status == "rejected" and v.note == "script changed: прошпиlena"
    # a mixed-script designation that is present in the draft (grade "173M1" with a Latin M) is no reason to reject
    b = "<table><tr><td>Машина 173Mм</td></tr></table>"
    assert judge("table", b, None, b, None, 5.0).status == "done"


def test_judge_reject_reason_names_edit_budget():
    a = "Отливки из серого чугуна марки СЧ20 охлаждают"
    v = judge("text", a, None, "Отливки из белого чугуна марки КЧ35 нагревают", None, 0.15, halluc_abs_chars=3)
    assert v.status == "rejected" and v.note.startswith("cer ") and " chars > " in v.note


def test_kept_fixes_drop_dash_only_and_unverified():
    from techbookocr.pipeline.arbiter import kept_fixes
    a = "Температура 1540-1570 °C, ааказу"
    v = judge("text", a, None, "Температура 1540–1570 °C, заказу", None, 0.15)
    fixes = [{"was": "1540-1570", "now": "1540–1570"}, {"was": "ааказу", "now": "заказу"},
             {"was": "нет в черновике", "now": "x"}]
    assert kept_fixes(fixes, [a], v) == [{"was": "ааказу", "now": "заказу"}]


def test_sanitize_fixes_reverts_digit_change():
    """Girshovich, p. 363: the arbiter "fixed" the correct "C + 1/3 Si" to "1/8": a value edit, not a typo fix."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    answer = "ТУ = C + <sup>1/8</sup> Si, %"
    fixes = [{"was": "C + 1/3 Si, %", "now": "C + <sup>1/8</sup> Si, %"}]
    text, kept, rejected = sanitize_fixes(answer, fixes, {}, ["ТУ = C + 1/3 Si, %"])
    assert text == "ТУ = C + 1/3 Si, %" and kept == [] and len(rejected) == 1
    # the same fix twice on a page (Girshovich, 0181R): both occurrences are rolled back
    answer2 = "<th>C + <sup>1/8</sup> Si</th><th>C + <sup>1/8</sup> Si</th>"
    fixes2 = [{"was": "C + 1/3 Si", "now": "C + <sup>1/8</sup> Si"}] * 2
    text2, _, rejected2 = sanitize_fixes(answer2, fixes2, {}, ["C + 1/3 Si, %"])
    assert "1/8" not in text2 and len(rejected2) == 2


def test_sanitize_fixes_keeps_subscript_digit_repairs():
    """From the Girshovich scans: dm3->dm2 (p. 403), C3H2->C8H2 (p. 471), No2->No (p. 706) are correct
    fixes of superscript/subscript marks. Only full-height digits are the risk zone."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    ok = [
        ({"was": "1 дм³", "now": "1 дм²"}, "на 1 дм²"),
        ({"was": "C<sub>3</sub>H<sub>2</sub>", "now": "C<sub>8</sub>H<sub>2</sub>"}, "0,04% C<sub>8</sub>H<sub>2</sub>"),
        ({"was": "№<sub>2</sub>", "now": "№"}, "кривой №"),
    ]
    for fix, answer in ok:
        text, kept, rejected = sanitize_fixes(answer, [fix], {}, [fix["was"]])
        assert not rejected and kept == [fix] and text == answer


def test_sanitize_fixes_reverts_word_dup_and_line_hyphen():
    """p. 305: a word doubled with a comma; p. 430: a word gets a hyphen inserted (hyphenation)."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    fixes = [{"was": "Крепления бобышек, пластиков, ребер", "now": "Крепления бобышек, пластиков, ребер, ребер"},
             {"was": "Органическое связующее", "now": "Органическое связу-ющее"}]
    answer = "Крепления бобышек, пластиков, ребер, ребер — Органическое связу-ющее"
    text, kept, rejected = sanitize_fixes(answer, fixes, {},
                                          ["Крепления бобышек, пластиков, ребер — Органическое связующее"])
    assert text == "Крепления бобышек, пластиков, ребер — Органическое связующее"
    assert [r["rejected"] for r in rejected] == ["duplicates word", "keeps line-break hyphen"]


def test_sanitize_fixes_reverts_doubled_operator_and_empty():
    """Girshovich, p. 615: "4,0×3,94" -> "4,0××3,94" and p. 432: an abbreviation -> empty."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    answer = "<td>4,0××3,94</td><td></td>"
    fixes = [{"was": "4,0×3,94", "now": "4,0××3,94"}, {"was": "КБЖ", "now": ""}]
    text, kept, rejected = sanitize_fixes(answer, fixes, {}, ["4,0×3,94 КБЖ"])
    assert "4,0×3,94" in text and "××" not in text and kept == [] and len(rejected) == 2


def test_sanitize_fixes_reverts_value_shift_chain():
    """Girshovich, p. 432: the "now" of one fix equals the "was" of the next, a shift of column values."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    answer = "<td>СФ-480</td><td>ФМС</td><td>ФПР-24</td>"
    fixes = [{"was": "КФ-40", "now": "СФ-480"}, {"was": "СФ-480", "now": "ФМС"}, {"was": "ФМС", "now": "ФПР-24"}]
    text, kept, rejected = sanitize_fixes(answer, fixes, {}, ["КФ-40 СФ-480 ФМС ФПР-24"])
    assert kept == [] and len(rejected) == 3 and "КФ-40" in text


def test_sanitize_fixes_reverts_rare_term_only_with_corpus():
    """Girshovich, p. 335: a misprint-like term replaced by a plain word. The term recurs across the book, so the fix is rejected;
    the same word seen only once is not considered a term."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    answer = "для крепления форм используют ужины"
    fixes = [{"was": "ужимины", "now": "ужины"}]
    dr = ["для крепления форм используют ужимины"]
    text, kept, rejected = sanitize_fixes(answer, fixes, {"ужимины": 3}, dr)
    assert "ужимины" in text and kept == [] and len(rejected) == 1
    text2, kept2, _ = sanitize_fixes(answer, fixes, {}, dr)
    assert kept2 == fixes and text2 == answer


def test_sanitize_fixes_keeps_real_misprint_and_script_fix():
    """Real misprints and Cyrillic/Latin normalization pass: a typo in a word, Latin Mo -> Cyrillic Mo."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    answer = "молотковый порошок, 10% Мо"
    fixes = [{"was": "перошок", "now": "порошок"}, {"was": "10% Mo", "now": "10% Мо"}]
    text, kept, rejected = sanitize_fixes(answer, fixes, {})
    assert text == answer and kept == fixes and rejected == []


def test_sanitize_fixes_reverts_deletion_span():
    """Girshovich, p. 754: "Nickel cast iron (N. N. Alexandrov)" -> "Nickel cast iron": text deletion."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    answer = "Никелевый чугун. Марки"
    fixes = [{"was": "Никелевый чугун (Н. Н. Александров)", "now": "Никелевый чугун"}]
    text, kept, rejected = sanitize_fixes(answer, fixes, {}, ["Никелевый чугун (Н. Н. Александров)"])
    assert "(Н. Н. Александров)" in text and kept == [] and len(rejected) == 1


def test_run_arbiter_reverts_bad_fix_and_reports(tmp_path):
    """End to end: a reply with a dangerous fix is rolled back to the printed text, the report marks it rejected."""
    st = new_state(tmp_path, names=("0001",))
    _disputed(st, ["0001"])
    reply = PARA.replace("400", "800") + '\nFIXES: [{"was": "400", "now": "800"}]'
    vlm = FakeVLM(lambda prompt: BlockResult(reply, raw=reply, seconds=1.0))
    run_arbiter(st, vlm, tmp_path / "work", CFG, "ru", TransportGuard(sleep=NO_SLEEP))
    b = st.blocks("0001")[0]
    assert b.final == PARA and "400" in b.final
    assert b.fixes == [{"was": "400", "now": "800", "rejected": "changes digits"}]
    assert "reverted" in (b.arbiter_note or "")
    st.close()


def test_run_arbiter_malformed_sketches_do_not_kill_stage(tmp_path):
    """A broken sketches entry on a block is a degenerate box, the stage goes on (the book does not fail because of one block)."""
    st = new_state(tmp_path, names=("0001",))
    st.set_layout("0001", [Block("Table", "<table><tr><td>1</td></tr></table>", (100, 100, 900, 300))],
                  status="done")
    blk = st.blocks("0001")[0]
    st.update_block(blk.id, decision="arbiter", consensus_status="done", arbiter_status="pending",
                    sketches=[{"path": "images/x.png"}, "мусор",
                              {"path": "images/y.png", "bbox": [50, 50, 60, 60]}])
    reply = "<table><tr><td>1</td></tr></table>\nFIXES: []"
    assert run_arbiter(st, FakeVLM(lambda p: BlockResult(reply, raw=reply)), tmp_path / "work", CFG, "ru",
                       TransportGuard(sleep=NO_SLEEP)) == 1
    b = st.blocks("0001")[0]
    assert b.arbiter_status == "done" and b.final.startswith("<table>")
    st.close()


def test_mark_sketches_and_prompt_rule():
    from PIL import Image
    from techbookocr.pipeline.arbiter import mark_sketches
    page = Image.new("L", (400, 400), 255)
    out = mark_sketches(page, [(50, 50, 250, 250)])
    assert out.mode == "RGB" and out.getpixel((150, 50)) == (230, 0, 0) and page.getpixel((150, 50)) == 255
    assert 'Put <img n="k">' in build_prompt("table", "ru", ["<table></table>"], sketches=3)
    assert "numbered 1..3" in build_prompt("table", "ru", ["<table></table>"], sketches=3)
    assert "<img n" not in build_prompt("table", "ru", ["<table></table>"])
    assert "<img n" not in build_prompt("text", "ru", ["абзац"], sketches=3)


def test_judge_ignores_sketch_numbers_in_table():
    a = "<table><tr><td>Светлая<br>Рис. 1а</td><td>Гладкая</td></tr></table>"
    ans = '<table><tr><td>Светлая<br><img n="1"><br>Рис. 1а</td><td>Гладкая</td></tr></table>'
    v = judge("table", a, None, ans, None, 0.15, halluc_abs_chars=0)
    assert v.status == "done" and v.final == ans


def test_judge_ignores_sketch_number_variants_and_mark_skips_bad_box():
    from PIL import Image
    from techbookocr.pipeline.arbiter import mark_sketches
    a = "<table><tr><td>Светлая</td></tr></table>"
    for tag in ("<img n='1'>", '<img n="1" alt="x">', '<img n="1"/>'):
        assert judge("table", a, None, f"<table><tr><td>Светлая{tag}</td></tr></table>", None, 0.15,
                     halluc_abs_chars=0).status == "done"
    out = mark_sketches(Image.new("L", (100, 100), 255), [(50, 50, 10, 10), (10, 10, 60, 60)])
    assert out.getpixel((30, 10)) == (230, 0, 0)


def test_sanitize_fixes_revert_respects_token_boundaries():
    """NBS RP2560, p. 17: rolling back ".1089" must not turn the printed "0.1089" into "00.1089"."""
    from techbookocr.pipeline.arbiter import sanitize_fixes
    fixes = [{"was": "0.1009", "now": ".1089"}]
    d = ["<td>0.1009</td>", "<td>0.1009</td>"]
    text, _, _ = sanitize_fixes("<td>0.1089</td>", fixes, {}, d)
    assert text == "<td>0.1089</td>" and "00." not in text
    text, _, rej = sanitize_fixes("<td>.1089</td>", fixes, {}, d)
    assert text == "<td>0.1009</td>" and len(rej) == 1
    text, _, _ = sanitize_fixes("$0.1089$", fixes, {}, d)
    assert text == "$0.1089$"
    # "now" is part of a longer number
    f2 = [{"was": "1/3", "now": "1/8"}]
    text, _, _ = sanitize_fixes("<td>11/8</td>", f2, {}, ["1/3"])
    assert text == "<td>11/8</td>"
    text, _, _ = sanitize_fixes("<td>1/8</td>", f2, {}, ["1/3"])
    assert text == "<td>1/3</td>"
    # Cyrillic: "now" is a piece of another word
    f3 = [{"was": "ужимины", "now": "ужины"}]
    text, _, _ = sanitize_fixes("неужины и ужины", f3, {"ужимины": 3}, ["ужимины"])
    assert text == "неужины и ужимины"


def test_sanitize_fixes_drops_leading_zero_typography():
    """RP2560: "0.1052" <-> ".1052" is the same number, typography: neither a fix nor a rejection."""
    from techbookocr.pipeline.arbiter import sanitize_fixes, _same_number
    fixes = [{"was": "0.1052", "now": ".1052"}, {"was": "0,15", "now": ",15"}]
    text, kept, rej = sanitize_fixes("<td>.1052</td><td>,15</td>", fixes, {}, ["<td>0.1052</td><td>0,15</td>"])
    assert rej == [] and kept == [] and text == "<td>.1052</td><td>,15</td>"
    assert not _same_number("0.15", "0.150") and not _same_number("1.5", "15")
    bad = [{"was": "0.1052", "now": "0.1062"}]
    text, _, rej = sanitize_fixes("<td>0.1062</td>", bad, {}, ["<td>0.1052</td>"])
    assert len(rej) == 1 and text == "<td>0.1052</td>"
