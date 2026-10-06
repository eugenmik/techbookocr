from techbookocr.pipeline.assemble import (anchor, book_meta, fill_sketches, link_footnotes, render_book,
                                       title_author_year)
from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.postproc.run import PostResult
from techbookocr.pipeline.state import PageRow

S = ["images/p1_tab0_cell1.png", "images/p1_tab0_cell2.png"]


def test_fill_sketches_by_placeholders():
    html, extra, note = fill_sketches("<table><tr><td><img></td><td>5</td><td><img></td></tr></table>", S)
    assert html == (f'<table><tr><td><img src="{S[0]}"></td><td>5</td>'
                    f'<td><img src="{S[1]}"></td></tr></table>')
    assert extra == [] and note is None


def test_fill_sketches_by_chandra_cells():
    final = "<table><tr><td>а</td><td>б</td></tr><tr><td>в</td><td>г</td></tr></table>"  # arbiter result without <img>
    chandra = "<table><tr><td><img></td><td>б</td></tr><tr><td>в</td><td><img></td></tr></table>"
    html, extra, note = fill_sketches(final, S, chandra)
    assert html.count("<img") == 2 and extra == [] and note is None
    assert f'<td>а<img src="{S[0]}"></td>' in html and f'<td>г<img src="{S[1]}"></td>' in html


def test_fill_sketches_mismatch_appends_after_table():
    html, extra, note = fill_sketches("<table><tr><td><img>текст</td></tr></table>", S, None)
    assert "<img" not in html and "<td>текст</td>" in html and extra == S
    assert note == "2 sketches, 1 <img> slots: sketches placed after the table"
    html, extra, note = fill_sketches("<table><tr><td><img></td></tr></table>", [])
    assert "<img" not in html and extra == [] and note == "0 sketches, 1 <img> slots: empty <img> removed"
    html, extra, note = fill_sketches("не таблица", S)
    assert html == "не таблица" and extra == S and note == "table not parsed, sketches placed after it"


def test_render_book_malformed_sketches_do_not_crash():
    """A broken sketch entry (no path, not a dict): its place in the numbering is kept, assembly does not fail."""
    items = [Item(1, "0001", 0, "Table", '<table><tr><td><img n="1"></td></tr></table>',
                  sketches=[{"bbox": [0, 0, 5, 5]}, "мусор", {"path": "images/cell3.png", "bbox": [0, 0, 5, 5]}])]
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), [PageRow(name="0001", idx=0)])
    assert "<table>" in md and "images/cell3.png" in md


def test_link_footnotes():
    items = [Item(1, "0001", 0, "Text", "Чугун марки СЧ20* и сталь**."), Item(2, "0001", 1, "Footnote", "* По ГОСТ 1412."),
             Item(3, "0001", 2, "Footnote", "** Устаревшая марка."), Item(4, "0001", 3, "Footnote", "Без маркера")]
    n, defs = link_footnotes(items, 5)
    assert n == 7 and items[0].text == "Чугун марки СЧ20[^5] и сталь[^6]."
    assert defs == {2: "[^5]: По ГОСТ 1412.", 3: "[^6]: Устаревшая марка."}


def test_render_book_anchors_stitch_figures_formulas_tables():
    pages = [PageRow(name="0001", idx=0), PageRow(name="0002", idx=1), PageRow(name="0003", idx=2)]
    items = [Item(1, "0001", 0, "Section-header", "Глава 1"),
             Item(2, "0001", 1, "Picture", "", image="images/p0001_fig1.png"),
             Item(3, "0001", 2, "Caption", "Рис. I.28. Структура [чугуна]"),
             Item(4, "0001", 3, "Formula", "$$\nW = 1\n$$"),
             Item(5, "0001", 4, "Text", "Абзац продолжается"),
             Item(6, "0001", 5, "Footnote", "Сноска без маркера."),
             Item(7, "0002", 0, "Text", "на следующей странице.", join_to=5),
             Item(8, "0002", 1, "Table", "<table><tr><td><img></td></tr></table>",
                  sketches=[{"path": "images/p0002_tab1_cell1.png", "bbox": [0, 0, 1, 1]}], note="continues: table 4")]
    post = PostResult(items=items, printed={"0001": "15", "0002": "16", "0003": None}, spell=None)
    md, notes = render_book(post, pages)
    assert md == (
        "<!-- page: 15 scan: 0001 -->\n\n## Глава 1\n\n![Рис. I.28. Структура чугуна](images/p0001_fig1.png)\n\n"
        "Рис. I.28. Структура [чугуна]\n\n$$\nW = 1\n$$\n\n"
        "Сноска без маркера.\n\n"
        "Абзац продолжается <!-- page: 16 scan: 0002 --> на следующей странице.\n\n"
        "<!-- continues: table 4 -->\n\n<table><tr><td><img src=\"images/p0002_tab1_cell1.png\"></td></tr></table>\n\n"
        "<!-- page: ? scan: 0003 -->\n")
    assert notes == []


def test_render_book_footnote_definitions_end_page():
    pages = [PageRow(name="0001", idx=0), PageRow(name="0002", idx=1)]
    items = [Item(1, "0001", 0, "Text", "Сталь*."), Item(2, "0001", 1, "Footnote", "* Примечание."),
             Item(3, "0002", 0, "Text", "Новый абзац.")]
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), pages)
    assert md == ("<!-- page: ? scan: 0001 -->\n\nСталь[^1].\n\n[^1]: Примечание.\n\n"
                  "<!-- page: ? scan: 0002 -->\n\nНовый абзац.\n")


def test_fill_sketches_multiple_tables_and_text_strict():
    html = "Text <table><tr><td><img></td></tr></table> middle <img> <table><tr><td><img></td></tr></table> end"
    result, extra, note = fill_sketches(html, S)  # 3 slots, 2 sketches: in reading order, the extra slot is removed
    assert result == (f'Text <table><tr><td><img src="{S[0]}"></td></tr></table> middle <img src="{S[1]}"> '
                      '<table><tr><td></td></tr></table> end')
    assert extra == [] and note == "2 sketches, 3 <img> slots: extra empty <img> removed"
    html2 = "<table><tr><td><img></td></tr></table><table><tr><td>q</td></tr></table>"
    result, extra, note = fill_sketches(html2, S)
    assert result == f'<table><tr><td><img src="{S[0]}"></td></tr></table><table><tr><td>q</td></tr></table>'
    assert extra == [S[1]] and note == "2 sketches, 1 <img> slots: extra sketches appended after tables"


def test_fill_sketches_div_handling():
    # the original <div> is neither duplicated nor lost; text/tails are kept, special characters are escaped
    html = "<div class='a'><table><tr><td><img></td><td>a &lt; b</td></tr></table></div>"
    result, extra, note = fill_sketches(html, S[:1])
    assert result == f'<div class="a"><table><tr><td><img src="{S[0]}"></td><td>a &lt; b</td></tr></table></div>'
    assert extra == [] and note is None
    # a legitimate <div> in a cell and an input without <div> are untouched
    html = "<table><tr><td><div>x</div></td></tr></table>"
    assert fill_sketches(html, []) == (html, [], None)
    html = "Выше &amp; ниже <table><tr><td><div>x</div><img></td></tr></table> после"
    result, extra, note = fill_sketches(html, S[:1])
    assert result == (f'Выше &amp; ниже <table><tr><td><div>x</div><img src="{S[0]}"></td></tr></table> после')
    assert extra == [] and note is None


def test_fill_sketches_loose_img_outside_table():
    result, extra, note = fill_sketches("<p>до</p><img><table><tr><td>x</td></tr></table>", S[:1])
    assert result == f'<p>до</p><img src="{S[0]}"><table><tr><td>x</td></tr></table>' and extra == [] and note is None
    result, extra, note = fill_sketches("<p>до</p><img><table><tr><td>x</td></tr></table>", S)
    assert result == "<p>до</p><table><tr><td>x</td></tr></table>" and extra == S
    assert note == "2 sketches, 1 <img> slots: sketches placed after the table"
    result, extra, note = fill_sketches("текст <img> конец", [])
    assert result == "текст  конец" and extra == [] and note == "0 sketches, 1 <img> slots: empty <img> removed"
    result, extra, note = fill_sketches("текст <img> конец", S)
    assert "<img" not in result and extra == S and note == "table not parsed, sketches placed after it"


def test_fill_sketches_chandra_counts_only_srcless_img():
    final = "<table><tr><td>а</td><td>б</td></tr></table>"
    chandra = '<table><tr><td><img src="real.png"></td><td><img></td></tr></table>'  # img with src is not a sketch slot
    html, extra, note = fill_sketches(final, S[:1], chandra)
    assert html == f'<table><tr><td>а</td><td>б<img src="{S[0]}"></td></tr></table>'
    assert extra == [] and note is None
    # two sketches, but only one src-less img in B -> no match, sketches go after the table
    html, extra, note = fill_sketches(final, S, chandra)
    assert html == final and extra == S and note == "2 sketches, 0 <img> slots: sketches placed after the table"


def test_link_footnotes_unlinked_asterisk_not_linked():
    items = [Item(1, "0001", 0, "Text", "Text without markers."),
             Item(2, "0001", 1, "Footnote", "* This is a standalone asterisk")]
    n, defs = link_footnotes(items, 1)
    assert n == 1 and defs == {}


def test_render_book_escapes_unlinked_asterisk_footnote():
    pages = [PageRow(name="0001", idx=0)]
    items = [Item(1, "0001", 0, "Text", "Текст без маркеров."), Item(2, "0001", 1, "Footnote", "* Сноска сирота")]
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), pages)
    assert md == "<!-- page: ? scan: 0001 -->\n\nТекст без маркеров.\n\n\\* Сноска сирота\n"
    assert items[1].text == "* Сноска сирота"


def _fn_pages(n):
    return [PageRow(name=f"000{i}", idx=i - 1) for i in range(1, n + 1)]


def test_stitch_footnote_defs_page1_only():
    items = [Item(1, "0001", 0, "Text", "Абзац*"), Item(2, "0001", 1, "Footnote", "* Сн1."),
             Item(3, "0001", 2, "Text", "продолжается"), Item(4, "0002", 0, "Text", "дальше.", join_to=3),
             Item(5, "0002", 1, "Text", "Новый.")]
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), _fn_pages(2))
    assert md == ("<!-- page: ? scan: 0001 -->\n\nАбзац[^1]\n\n[^1]: Сн1.\n\n"
                  "продолжается <!-- page: ? scan: 0002 --> дальше.\n\nНовый.\n")
    assert md.count("[^1]:") == 1


def test_stitch_footnote_defs_both_pages():
    items = [Item(1, "0001", 0, "Text", "А*"), Item(2, "0001", 1, "Footnote", "* Сн1."),
             Item(3, "0001", 2, "Text", "хвост"), Item(4, "0002", 0, "Text", "конец.", join_to=3),
             Item(5, "0002", 1, "Text", "Б**"), Item(6, "0002", 2, "Footnote", "** Сн2."),
             Item(7, "0003", 0, "Text", "В.")]
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), _fn_pages(3))
    assert md == ("<!-- page: ? scan: 0001 -->\n\nА[^1]\n\n[^1]: Сн1.\n\nхвост <!-- page: ? scan: 0002 --> конец.\n\n"
                  "Б[^2]\n\n[^2]: Сн2.\n\n<!-- page: ? scan: 0003 -->\n\nВ.\n")
    assert md.count("[^1]:") == 1 and md.count("[^2]:") == 1


def test_stitch_footnote_defs_chain_of_three():
    items = [Item(1, "0001", 0, "Text", "А*"), Item(2, "0001", 1, "Footnote", "* Сн1."),
             Item(3, "0001", 2, "Text", "один"),
             Item(4, "0002", 0, "Text", "два", join_to=3), Item(5, "0002", 1, "Text", "Б**"),
             Item(6, "0002", 2, "Footnote", "** Сн2."), Item(7, "0002", 3, "Text", "три"),
             Item(8, "0003", 0, "Text", "четыре В***", join_to=7), Item(9, "0003", 1, "Footnote", "*** Сн3.")]
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), _fn_pages(3))
    assert md == ("<!-- page: ? scan: 0001 -->\n\nА[^1]\n\n[^1]: Сн1.\n\nодин <!-- page: ? scan: 0002 --> два\n\n"
                  "Б[^2]\n\n[^2]: Сн2.\n\nтри <!-- page: ? scan: 0003 --> четыре В[^3]\n\n[^3]: Сн3.\n")
    for n in (1, 2, 3):
        assert md.count(f"[^{n}]:") == 1


def test_title_author_year_and_meta():
    assert title_author_year("Гиршович_Справочник по чугунному литью_1978") == (
        "Справочник по чугунному литью", "Гиршович", 1978)
    assert title_author_year("Сафронов - Справочник по литейному оборудованию") == (
        "Справочник по литейному оборудованию", "Сафронов", None)
    stem = "Воронин Ю.Ф., Камаев В.А. Атлас литейных дефектов. Черные сплавы"
    assert title_author_year(stem) == (stem, None, None)
    pages = [PageRow(name="0001", idx=0)]
    meta = book_meta("Гиршович_Справочник по чугунному литью_1978", "test_books/g.djvu", pages, {"0001": "5"},
                     "ru", "cascade", {"layout": "dots_mocr"}, {"pages": 1})
    assert meta["author"] == "Гиршович" and meta["year"] == 1978 and meta["title"] == "Справочник по чугунному литью"
    assert meta["page_map"] == [{"scan": "0001", "printed": "5"}] and meta["pages"] == 1
    assert meta["lang"] == ["ru"] and meta["models"] == {"layout": "dots_mocr"} and meta["quality"] == {"pages": 1}
    assert anchor(pages[0], "5") == "<!-- page: 5 scan: 0001 -->"


def test_link_footnotes_marker_after_space():
    items = [Item(1, "p", 0, "Text", "содержание Cu до 15% **. И далее вверх ¹ и всё."),
             Item(2, "p", 1, "Footnote", "** По последним данным."), Item(3, "p", 2, "Footnote", "¹ Частота выше.")]
    n, defs = link_footnotes(items, 1)
    assert n == 3 and items[0].text == "содержание Cu до 15%[^1]. И далее вверх[^2] и всё."
    assert defs == {2: "[^1]: По последним данным.", 3: "[^2]: Частота выше."}


def test_link_footnotes_space_marker_not_inside_expression():
    items = [Item(1, "p", 0, "Text", "умножить * на два"), Item(2, "p", 1, "Footnote", "* Сноска.")]
    n, defs = link_footnotes(items, 1)
    assert defs == {} and items[0].text == "умножить * на два"


def test_link_footnotes_marker_in_table_cells():
    html = '<table><tr><td>Производительность *</td></tr><tr><td>1 730 **</td></tr></table>'
    items = [Item(1, "p", 0, "Table", html), Item(2, "p", 1, "Footnote", "* Диаметр 16 мм."),
             Item(3, "p", 2, "Footnote", "** Масса без шкафов.")]
    n, defs = link_footnotes(items, 1)
    assert items[0].text == ('<table><tr><td>Производительность[^1]</td></tr><tr><td>1 730[^2]</td></tr></table>')
    assert defs == {2: "[^1]: Диаметр 16 мм.", 3: "[^2]: Масса без шкафов."}


def test_stitched_paragraph_keeps_footnote_defs_on_their_page():
    # saf-0100L/R: the paragraph is stitched, but page L footnotes precede it, in section L
    pages = [PageRow(name="L", idx=0), PageRow(name="R", idx=1)]
    items = [Item(1, "L", 0, "Text", "Пескометание¹ продолжается"), Item(2, "L", 1, "Footnote", "¹ Частота выше."),
             Item(3, "R", 0, "Text", "на следующей странице."), Item(4, "R", 1, "Text", "Дальше.")]
    items[2].join_to = 1
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), pages)
    head, tail = md.split("<!-- page: ? scan: R -->")
    assert "[^1]: Частота выше." in head and "[^1]: Частота выше." not in tail
    assert "Пескометание[^1] продолжается" in md and tail.strip().startswith("на следующей странице.")
    assert md.index("[^1]: Частота") < md.index("Пескометание[^1]")


def test_stitch_still_joins_when_page_has_no_footnotes():
    pages = [PageRow(name="L", idx=0), PageRow(name="R", idx=1)]
    items = [Item(1, "L", 0, "Text", "продолжается"), Item(3, "R", 0, "Text", "дальше.", join_to=1)]
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), pages)
    assert "продолжается <!-- page: ? scan: R --> дальше." in md


def test_superscript_marker_not_linked_after_unit():
    items = [Item(1, "p", 0, "Table", "<table><tr><td>Объем, м³</td><td>5 м²</td></tr></table>"),
             Item(2, "p", 1, "Text", "Расход 5 т/ч³ и 20 мм² площади."), Item(3, "p", 2, "Footnote", "³ По данным завода.")]
    n, defs = link_footnotes(items, 1)
    assert defs == {} and "м³" in items[0].text and "мм²" in items[1].text
    items = [Item(1, "p", 0, "Text", "Модуль упругости E³ принят."), Item(2, "p", 1, "Footnote", "³ По данным.")]
    assert link_footnotes(items, 1)[1] == {2: "[^1]: По данным."}


def test_superscript_one_after_unit_is_a_marker_but_two_three_are_not():
    items = [Item(1, "p", 0, "Text", "Влажность до 5 %¹ и объем 3 м³."), Item(2, "p", 1, "Footnote", "¹ По ГОСТ.")]
    assert link_footnotes(items, 1)[1] == {2: "[^1]: По ГОСТ."} and "м³" in items[0].text
    items = [Item(1, "p", 0, "Text", "объем 3 м³."), Item(2, "p", 1, "Footnote", "³ Сноска.")]
    assert link_footnotes(items, 1)[1] == {}


def test_fill_sketches_by_figure_captions_in_cells():
    """Voronin atlas: neither the result nor Chandra has <img>, but a cell has captions "Fig. 1a<br>Fig. 1b";
    the sketches go before their captions in reading order."""
    final = ("<table><tr><td>1</td><td>Светлая<br>Рис. 1а<br>Рис. 1б</td><td>Гладкая</td></tr>"
             "<tr><td colspan=\"2\">Причины. См. Рис. 1а</td></tr></table>")
    html, extra, note = fill_sketches(final, S, None)
    assert extra == [] and note is None
    assert f'<td>Светлая<br><img src="{S[0]}"><br>Рис. 1а<br><img src="{S[1]}"><br>Рис. 1б</td>' in html
    assert "<td colspan=\"2\">Причины. См. Рис. 1а</td>" in html  # a reference in the text is not a caption


def test_fill_sketches_captions_count_mismatch_appends_after_table():
    final = "<table><tr><td>Рис. 1а<br>Рис. 1б<br>Рис. 1в</td></tr></table>"
    html, extra, note = fill_sketches(final, S, None)
    assert "<img" not in html and extra == S and note == "2 sketches, 0 <img> slots: sketches placed after the table"


def test_fill_sketches_by_arbiter_numbers():
    """Voronin p. 83: sketches in two columns, cell order differs from page row order: the arbiter places <img n>."""
    s3 = S + ["images/p1_tab0_cell3.png"]
    final = ('<table><tr><td>Рис. 2.1<img n="2"></td><td>серый<img n="1"></td><td><img n="9"><img n="2"></td>'
             '<td><img></td></tr></table>')
    html, extra, note = fill_sketches(final, s3, None)
    assert f'<td>Рис. 2.1<img src="{s3[1]}"></td><td>серый<img src="{s3[0]}"></td><td></td><td></td>' in html
    assert extra == [s3[2]] and note == "3 sketches, 2 placed by arbiter: the rest appended after the table"
    html, extra, note = fill_sketches('<table><tr><td><img n="1"><img n="2"></td></tr></table>', S, None)
    assert html.count("src=") == 2 and extra == [] and note is None


def test_fill_sketches_non_ascii_number_does_not_crash():
    html, extra, note = fill_sketches('<table><tr><td><img n="²">а</td></tr></table>', S, None)
    assert "<img" not in html and extra == S


def test_book_meta_timings():
    meta = book_meta("Автор - Книга", "src.djvu", [], {}, "ru", "fast", {}, {},
                     timings={"layout": 120.04, "arbiter": 30.0})
    assert meta["timings"] == {"layout": 120.0, "arbiter": 30.0}
    assert "timings" not in book_meta("b", "s", [], {}, "ru", "fast", {}, {})
