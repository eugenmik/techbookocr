from techbookocr.pipeline.lang import detect_lang, sample_texts
from techbookocr.pipeline.state import BlockRow, PageRow


def test_detect_lang():
    assert detect_lang(["Чугун марки СЧ20 содержит углерод."]) == "ru"
    assert detect_lang(["The cast iron is poured into the mould and cooled."]) == "en"
    assert detect_lang(["Das Gusseisen wird in die Form gegossen und gekühlt."]) == "de"
    assert detect_lang([]) == "ru"
    assert detect_lang(["Доля $W_\\text{graphite} = \\frac{n}{N}$ мала"]) == "ru"  # LaTeX does not count
    assert detect_lang(["simple text without keywords"]) == "ru"  # tie/zero hits → ru


def test_sample_texts():
    pages = [PageRow(name="b", idx=1), PageRow(name="a", idx=0), PageRow(name="c", idx=2)]
    blocks = [BlockRow(id=1, page="a", ord=0, category="Text", text_a="один"),
              BlockRow(id=2, page="a", ord=1, category="Table", text_a="<table>"),
              BlockRow(id=3, page="b", ord=0, category="Title", text_a="два"),
              BlockRow(id=4, page="c", ord=0, category="Text", text_a="три")]
    assert sample_texts(pages, blocks, 2) == ["один", "два"]
