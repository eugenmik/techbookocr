from techbookocr.pipeline.postproc.run import postprocess
from techbookocr.pipeline.state import BlockRow, PageRow


def test_postprocess_end_to_end():
    pages = [PageRow(name="0001", idx=0), PageRow(name="0002", idx=1)]
    blocks = [
        BlockRow(id=1, page="0001", ord=0, category="Page-header", text_a="Таблица 47", bbox=(800, 20, 990, 60)),
        BlockRow(id=2, page="0001", ord=1, category="Table", text_a="<table><tr><td>173M1</td></tr></table>",
                 final="<table><tr><td>Сито 173M1</td></tr></table>", bbox=(50, 100, 950, 600),
                 sketches=[{"path": "images/p0001_tab1_cell1.png", "bbox": [60, 110, 200, 200]}],
                 text_b="<table><tr><td><img></td></tr></table>", drafts_status="done"),
        BlockRow(id=3, page="0001", ord=2, category="Picture", bbox=(60, 110, 200, 200), parent=2),
        BlockRow(id=4, page="0001", ord=3, category="Text", text_a="Структура ме-", final="Структура ме-",
                 bbox=(50, 700, 950, 900)),
        BlockRow(id=5, page="0001", ord=4, category="Page-footer", text_a="183", bbox=(450, 1350, 550, 1390)),
        BlockRow(id=6, page="0002", ord=0, category="Text", final="талла и отрица-тельных значений; металла",
                 bbox=(50, 100, 950, 300)),
        BlockRow(id=7, page="0002", ord=1, category="Page-footer", text_a="184", bbox=(450, 1350, 550, 1390)),
    ]
    res = postprocess(pages, blocks, speller=None)
    assert [(it.id, it.category) for it in res.items] == [(1, "Caption"), (2, "Table"), (4, "Text"), (6, "Text")]
    table = res.items[1]
    assert table.text == "<table><tr><td>Сито 173М1</td></tr></table>"
    assert table.text_b == "<table><tr><td><img></td></tr></table>" and table.sketches[0]["path"].endswith("cell1.png")
    assert res.items[2].text == "Структура" and res.items[3].text.startswith("металла и отрица-тельных")
    assert res.items[3].join_to == 4 and res.stitched == 1
    assert res.printed == {"0001": "183", "0002": "184"} and res.spell is None


class _Speller:
    def known(self, w):
        return w.lower() in {"отрицательных", "значений", "металла"}


def test_postprocess_uses_speller_for_hyphens_and_stats():
    pages = [PageRow(name="0001", idx=0)]
    blocks = [BlockRow(id=1, page="0001", ord=0, category="Text", final="отрица-тельных значений и чгун")]
    res = postprocess(pages, blocks, _Speller())
    assert res.items[0].text == "отрицательных значений и чгун"
    assert res.spell.checked == 3 and res.spell.unknown == 1 and res.spell.top[0][0] == "чгун"


def test_compound_word_stays_hyphenated():
    """A compound word appearing twice should stay hyphenated after postprocessing."""
    pages = [PageRow(name="0001", idx=0)]
    # the hyphenated word "blue-green" appears twice in the book
    blocks = [BlockRow(id=1, page="0001", ord=0, category="Text",
                       final="Цвет был сине-зелёный и сине-зелёный.")]
    res = postprocess(pages, blocks, speller=None)
    # The compound should stay hyphenated because it appears >= 2 times
    assert "сине-зелёный" in res.items[0].text
    # Check that it wasn't merged
    assert "синезелёный" not in res.items[0].text


def test_span_merge_gated_by_pipeline_flag():
    """The colspan rule is enabled by the pipeline.span_single_value key; off by default
    (measured on two books: 12/15 correct < threshold 13/15, see eval/table-spans.md)."""
    from techbookocr.config import PipelineConfig
    pages = [PageRow(name="0001", idx=0)]
    html = "<table><tr><td>высота</td><td></td><td>500</td></tr></table>"
    dash = "<table><tr><td>Развес</td><td>—</td><td>10—500</td><td>—</td><td>x</td></tr></table>"
    blocks = [BlockRow(id=1, page="0001", ord=0, category="Table", final=html),
              BlockRow(id=2, page="0001", ord=1, category="Table", final=dash)]
    off = postprocess(pages, blocks, speller=None)
    assert "colspan" not in off.items[0].text and off.spans == {}
    # suspicious dashes are always reported: this is a report, not a fix
    assert off.suspects == [("0001", 1, 'row "Развес": 2 dashes next to value "10—500"')]
    on = postprocess(pages, blocks, speller=None, cfg=PipelineConfig(span_single_value=True))
    assert 'colspan="2"' in on.items[0].text and on.spans


def test_postprocess_table_footnotes_and_fragments():
    pages = [PageRow(name="0001", idx=0)]
    html = ('<table><tr><td>a</td><td>b</td></tr><tfoot><tr><td colspan="2">* Сноска.</td></tr></tfoot></table>'
            '<table><tr><td>c</td><td>d</td></tr></table>')
    blocks = [BlockRow(id=1, page="0001", ord=0, category="Table", final=html, bbox=(0, 0, 10, 10))]
    res = postprocess(pages, blocks, speller=None)
    assert [it.category for it in res.items] == ["Table", "Footnote"]
    assert res.items[0].text.count("<table") == 1 and "tfoot" not in res.items[0].text
    assert res.items[1].text == "* Сноска."
