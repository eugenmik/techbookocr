from techbookocr.models.markdown import blocks_to_markdown
from techbookocr.models.types import Block


def test_blocks_to_markdown():
    blocks = [
        Block("Page-header", "Газовые раковины 61"),
        Block("Section-header", "§7. Снижение содержания шлака в стали"),
        Block("Text", "В ванну плавильной печи попадают вещества [24]."),
        Block("List-item", "1. Использовать чистые шихтовые материалы."),
        Block("List-item", "повышение расхода воздуха"),
        Block("Formula", r"W_г = \frac{n_{ср}}{N_{общ}} 100"),
        Block("Table", "<table><tr><td>1</td></tr></table>"),
        Block("Picture", "", bbox=(10, 20, 110, 220)),
        Block("Caption", "Рис. I.28. Структура чугуна"),
        Block("Page-footer", "61"),
    ]
    md = blocks_to_markdown(blocks, picture_ref=lambda b: f"images/fig_{b.bbox[0]}.png")
    assert md == (
        "## §7. Снижение содержания шлака в стали\n\n"
        "В ванну плавильной печи попадают вещества [24].\n\n"
        "1. Использовать чистые шихтовые материалы.\n\n"
        "- повышение расхода воздуха\n\n"
        "$$\nW_г = \\frac{n_{ср}}{N_{общ}} 100\n$$\n\n"
        "<table><tr><td>1</td></tr></table>\n\n"
        "![](images/fig_10.png)\n\n"
        "Рис. I.28. Структура чугуна\n"
    )


def test_formula_already_delimited_kept():
    md = blocks_to_markdown([Block("Formula", "$$x=1$$")])
    assert md == "$$\nx=1\n$$\n"


def test_title_and_picture_without_ref():
    md = blocks_to_markdown([Block("Title", "Атлас"), Block("Picture", "")])
    assert md == "# Атлас\n\n![]()\n"


def test_formula_multiple_inline_kept_as_text():
    assert blocks_to_markdown([Block("Formula", "$a$ and $b$")]) == "$a$ and $b$\n"
    assert blocks_to_markdown([Block("Formula", "$$a$$ и $$b$$")]) == "$$a$$ и $$b$$\n"


def test_formula_single_inline_and_bracket_delimiters_stripped():
    assert blocks_to_markdown([Block("Formula", "$x_1$")]) == "$$\nx_1\n$$\n"
    assert blocks_to_markdown([Block("Formula", r"\[x+1\]")]) == "$$\nx+1\n$$\n"
    assert blocks_to_markdown([Block("Formula", r"$a\$b$")]) == "$$\na\\$b\n$$\n"


def test_empty_formula_skipped():
    for t in ("", "  ", "$$$$", "$$"):
        assert blocks_to_markdown([Block("Formula", t)]) == ""
