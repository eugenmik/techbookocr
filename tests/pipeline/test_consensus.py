from techbookocr.models.types import Block
from techbookocr.pipeline.consensus import (canonical_formula, canonical_table, canonical_text, cer, decide,
                                        run_consensus, same_numbers)
from tests.pipeline.fakes import new_state

LONG = ("Технические характеристики барабанных полигональных сит: производительность 40 т/ч, "
        "частота вращения барабана 12 об/мин, мощность привода 4,5 кВт, масса сита {} кг. "
        "Сито устанавливают на опорной раме и закрывают кожухом из листовой стали толщиной 2 мм.")


def test_canonical_text_ignores_markup_homoglyphs_and_hyphenation():
    assert canonical_text("**Чугун** марки СЧ20") == canonical_text("Чугун марки СЧ20")
    assert canonical_text("чугyн") == canonical_text("чугун")  # Latin y
    assert canonical_text("отрица-тельных значений") == canonical_text("отрицательных значений")
    assert canonical_text("доля $W_\\text{г}$ мала") == canonical_text("доля $W_{г}$ мала")
    assert canonical_text("## Глава 1") == canonical_text("Глава 1")
    assert canonical_text("Сталь 20") != canonical_text("Сталь 30")


def test_canonical_formula():
    a = "$$\nW_\\text{г} = \\frac{n_{\\text{ср}}}{N_{\\text{общ}}} 100.\n$$"
    b = "\\[ W_{г}=\\frac{n_{ср}}{N_{общ}}\\,100. \\]"
    assert canonical_formula(a) == canonical_formula(b)
    assert canonical_formula("$x^2$") != canonical_formula("$x^3$")


def test_canonical_formula_braces_structure():
    # Braces preserve structure: \frac{12}{3} != \frac{1}{23}
    assert canonical_formula("$$\\frac{12}{3}$$") != canonical_formula("$$\\frac{1}{23}$$")
    # Multi-char subscripts/exponents: x^{12} != x^{1}2
    assert canonical_formula("$x^{12}$") != canonical_formula("$x^{1}2$")
    # Single char brace removal: x^{2} == x^2
    assert canonical_formula("$x^{2}$") == canonical_formula("$x^2$")
    # Single char subscript: W_{\text{g}} == W_g
    assert canonical_formula("$$W_{\\text{г}}$$") == canonical_formula("$$W_г$$")


def test_canonical_table():
    a = '<table><thead><tr><th>Марка</th><th rowspan="2">σ, МПа</th></tr></thead><tr><td>СЧ20</td></tr></table>'
    b = '<table><tr><td>Марка</td><td rowspan="2">σ, МПа</td></tr><tr><td>CЧ20</td></tr></table>'
    assert canonical_table(a) == canonical_table(b)
    c = '<table><tr><td>Марка</td><td colspan="2">σ, МПа</td></tr><tr><td>СЧ20</td></tr></table>'
    assert canonical_table(a) != canonical_table(c)
    assert canonical_table("<table><tr><td><img></td></tr></table>").endswith("[img]")


def test_cer_and_numbers():
    assert cer("", "") == 0.0 and cer("abc", "abc") == 0.0 and cer("abc", "") == 1.0
    assert same_numbers("размер 1 350 мм, 0,5%", "размер 1350 мм, 0,5 %")
    assert not same_numbers("4 930", "4 980")


def test_decide_text():
    assert decide("text", "Чугун марки СЧ20", "Чугун марки СЧ20", 0.01).decision == "accept"
    a = LONG.format("4 930")
    d = decide("text", a, a.replace("листовой", "листовои"), 0.01)
    assert d.decision == "accept" and 0 < d.cer <= 0.01 and d.final == a and d.final_source == "a"
    assert decide("text", "Чугун", "Чутун", 0.01).decision == "arbiter"  # short block: CER 0.2


def test_number_mismatch_goes_to_arbiter_even_below_tau():
    a, b = LONG.format("4 930"), LONG.format("4 980")
    d = decide("text", a, b, 0.01)
    assert d.cer < 0.01 and d.decision == "arbiter" and d.final is None


def test_decide_formula_table_page_missing_b_and_fast():
    assert decide("formula", "$$x^2$$", "\\[x^{2}\\]", 0.01).decision == "accept"
    assert decide("formula", "$$x^2$$", "$$x^3$$", 0.5).decision == "arbiter"  # numbers differ -> arbiter
    assert decide("formula", "$$x^2$$", "$$y^2$$", 0.5).decision == "accept"  # otherwise A by default
    t = "<table><tr><td>1</td></tr></table>"
    assert decide("table", t, t.replace("<td>", "<th>").replace("</td>", "</th>"), 0.01).decision == "accept"
    assert decide("table", t, "<table><tr><td>7</td></tr></table>", 0.99).decision == "arbiter"
    assert decide("text", "Абзац", None, 0.01).decision == "arbiter"
    assert decide("page", "", "Страница", 0.01).decision == "arbiter"
    nd = decide(None, "12", None, 0.01)
    assert nd.decision == "nodraft" and nd.final == "12"
    assert decide("text", "Абзац", None, 0.01, mode="fast").decision == "accept"
    assert decide("formula", "$$x$$", None, 0.01, mode="fast").decision == "accept"
    assert decide("table", t, None, 0.01, mode="fast").decision == "arbiter"


def test_decide_both_empty_goes_to_arbiter():
    # Both canonical A and B empty → arbiter
    assert decide("text", "", "", 0.01).decision == "arbiter"
    assert decide("formula", "$$$$", "\\[\\]", 0.01).decision == "arbiter"
    assert decide("table", "<table></table>", "<table></table>", 0.01).decision == "arbiter"


def test_decide_formula_defaults_to_a_and_arbitrates_only_unusable_a():
    from techbookocr.pipeline.consensus import formula_usable
    a = "$$W_{\\text{г}} = \\frac{n_{\\text{ср}}}{N}$$"
    b = "$$W_{\\Gamma} = \\frac{n_{c p}}{N}$$"
    d = decide("formula", a, b, 0.01)
    assert (d.decision, d.final, d.final_source) == ("accept", a, "a") and d.cer > 0
    assert decide("formula", a, None, 0.01).decision == "accept"  # no B: A is the result anyway
    assert decide("formula", "", b, 0.01).decision == "arbiter"
    assert decide("formula", "$$ $$", b, 0.01).decision == "arbiter"
    broken = "$$\\frac{1}{2$$"
    assert not formula_usable(broken) and decide("formula", broken, b, 0.01).decision == "arbiter"
    assert not formula_usable("$$\\begin{array}{c} 1 $$") and not formula_usable("$$\\left( x $$")


def test_decide_mode_validation():
    import pytest
    with pytest.raises(ValueError, match="mode must be"):
        decide("text", "a", "b", 0.01, mode="invalid")


def test_run_consensus(tmp_path):
    st = new_state(tmp_path, names=("0001",))
    st.set_layout("0001", [Block("Text", "Абзац текста", (1, 1, 9, 9)), Block("Formula", "$$x$$", (1, 10, 9, 19)),
                           Block("Page-footer", "12", (1, 20, 9, 29))], status="done")
    text, formula, footer = st.blocks("0001")
    st.update_block(text.id, text_b="Абзац текста", drafts_status="done")
    st.update_block(formula.id, text_b="looping…", drafts_status="failed", b_error="looping")
    assert run_consensus(st, 0.01) == {"accept": 2, "nodraft": 1}
    text, formula, footer = st.blocks("0001")
    assert (text.decision, text.final, text.arbiter_status) == ("accept", "Абзац текста", "skipped")
    assert (formula.decision, formula.final, formula.arbiter_status) == ("accept", "$$x$$", "skipped")
    assert (footer.decision, footer.final) == ("nodraft", "12")
    assert st.pending("consensus") == 0 and st.pending("arbiter") == 0
    st.close()


def test_formula_numbers_differ_goes_to_arbiter_but_spacing_and_subscripts_do_not():
    assert decide("formula", "$$N = 5520$$", "$$N = 5 5 2 0$$", 0.01).decision == "accept"
    assert decide("formula", "$$W_{\\text{г}} = 12$$", "$$W_{\\Gamma} = 12$$", 0.01).decision == "accept"
    assert decide("formula", "$$W_{\\mathrm{ср}} = 12$$", "$$W_{c p} = 12$$", 0.01).decision == "accept"
    d = decide("formula", "$$I = 0,25H$$", "$$I = 0,35H$$", 0.01)
    assert d.decision == "arbiter" and d.final is None
