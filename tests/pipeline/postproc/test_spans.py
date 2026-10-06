from PIL import Image, ImageDraw

from techbookocr.config import PipelineConfig
from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.postproc.tables import span_by_geometry, span_single_value


def table(html: str) -> Item:
    return Item(1, "0018R", 3, "Table", html)


def test_single_value_row_becomes_colspan():
    """Safronov, p. 39: the "height 500" value is printed centered across two columns, dots put it in the last one."""
    it = table("<table><tr><th>Параметр</th><th>НЛ453С</th><th>НЛ453С1</th></tr>"
               "<tr><td>высота</td><td></td><td>500</td></tr></table>")
    assert span_single_value([it]) == 1
    assert '<td colspan="2">500</td>' in it.text and it.text.count("<td") == 2
    assert it.spans == ['row "высота": 500 — one value spanning 2 columns']


def test_label_only_and_full_rows_untouched():
    """A section header row (flask sizes, mm:) and a regular row are left alone."""
    it = table("<table><tr><td>Размеры опок, мм:</td><td></td><td></td></tr>"
               "<tr><td>в свету</td><td>1600×1200</td><td>1600×1300</td></tr></table>")
    assert span_single_value([it]) == 0 and "colspan" not in it.text and it.spans == []


def test_rowspan_and_broken_html_safe():
    it = table('<table><tr><td rowspan="3">Опоки</td><td></td><td>500</td></tr></table>')
    assert span_single_value([it]) == 1 and '<td colspan="2">500</td>' in it.text
    broken = table("не таблица")
    assert span_single_value([broken]) == 0 and broken.text == "не таблица"


def test_suspect_invented_dashes():
    """Safronov, p. 44, table 15: "10—500" is printed across three columns, the model filled in dashes."""
    from techbookocr.pipeline.postproc.tables import suspect_invented_dashes
    it = table("<table><tr><td>Развес литья, кг</td><td>1,5—100</td><td>—</td><td>10—500</td><td>—</td></tr></table>")
    assert suspect_invented_dashes([it]) == [(1, 'row "Развес литья, кг": 2 dashes next to value "10—500"')]
    ok = table("<table><tr><td>Мощность</td><td>—</td><td>665</td><td>400</td><td>760</td></tr></table>")
    assert suspect_invented_dashes([ok]) == []


def _grid(vlines=(0, 100, 200, 300, 400, 499), value=(110, 390), dashes=((435, 55, 465, 60),)):
    """Crop of a 5-column x 3-row table in a grid: the value in the 2nd row band,
    dash rectangles, "10" "20" "30" "40" in the 3rd row."""
    img = Image.new("L", (500, 120), 255)
    d = ImageDraw.Draw(img)
    for x in vlines:
        d.line((x, 0, x, 119), fill=0)
    for y in (0, 40, 80, 119):
        d.line((0, y, 499, y), fill=0)
    for x in range(10, 80, 14):              # row labels are "text" strokes
        d.rectangle((x, 52, x + 7, 66), fill=0)
        d.rectangle((x, 92, x + 7, 106), fill=0)
    if value:                                # the "value" is a series of strokes, like letters
        for x in range(value[0], value[1], 14):
            d.rectangle((x, 52, min(x + 7, value[1]), 66), fill=0)
    for box in dashes:
        d.rectangle(box, fill=0)
    for x in (130, 230, 330, 430):
        d.rectangle((x, 92, x + 14, 106), fill=0)
        d.rectangle((x + 20, 92, x + 27, 106), fill=0)
    return img


def _geo_table(cells: str) -> Item:
    return Item(1, "0018R", 3, "Table",
                "<table><tr><td>Параметр</td><td>M1</td><td>M2</td><td>M3</td><td>M4</td></tr>" + cells +
                "<tr><td>Мощность</td><td>10</td><td>20</td><td>30</td><td>40</td></tr></table>",
                bbox=(0, 0, 500, 120))


def test_geometry_merges_value_row_and_drops_invented_dashes():
    """Safronov, p. 44: "10—500" is printed centered across three columns, the outer dashes are invented.
    The dash in the 4th column is printed and stays."""
    it = _geo_table("<tr><td>Развес литья</td><td>—</td><td>10—500</td><td>—</td><td>—</td></tr>")
    n = span_by_geometry([it], {"0018R": _grid()}, PipelineConfig(span_geometry=True))
    assert n == 1
    assert '<td colspan="3">10—500</td><td>—</td>' in it.text
    assert len(it.spans) == 1


def test_geometry_clears_dashes_without_ink():
    """Value spans columns 1-2; dashes in the 3rd and 4th have no ink, so they are invented and cleared."""
    it = _geo_table("<tr><td>Развес литья</td><td>—</td><td>10—500</td><td>—</td><td>—</td></tr>")
    n = span_by_geometry([it], {"0018R": _grid(value=(110, 290), dashes=())},
                         PipelineConfig(span_geometry=True))
    assert n == 1
    assert '<td colspan="2">10—500</td><td></td><td></td>' in it.text


def test_geometry_keeps_row_when_crossing_run_is_foreign():
    """Safronov, p. 134: "depth 1 475 - -": the dashes are printed, and the series across
    the boundary belongs to another row ("2 750" above); the value must not be merged."""
    img = _grid(value=None, dashes=())
    d = ImageDraw.Draw(img)
    for x in range(130, 180, 14):            # "1 475" is its own value inside column 1
        d.rectangle((x, 52, x + 7, 66), fill=0)
    d.rectangle((195, 56, 230, 60), fill=0)  # another row's series across the boundary 200
    for x0 in (250, 350, 430):               # printed dashes in columns 2-4
        d.rectangle((x0, 56, x0 + 24, 60), fill=0)
    it = _geo_table("<tr><td>заглубление</td><td>1 475</td><td>—</td><td>—</td><td>—</td></tr>")
    html = it.text
    n = span_by_geometry([it], {"0018R": img}, PipelineConfig(span_geometry=True))
    assert n == 0 and it.text == html and it.spans == []


def test_geometry_skips_table_when_rules_missing():
    """Fewer rulings than columns: the geometry is unreliable, the table is unchanged."""
    it = _geo_table("<tr><td>Развес литья</td><td>—</td><td>10—500</td><td>—</td><td>—</td></tr>")
    html = it.text
    n = span_by_geometry([it], {"0018R": _grid(vlines=(0, 200, 499))},
                         PipelineConfig(span_geometry=True))
    assert n == 0 and it.text == html and it.spans == []
