from techbookocr.models.adapters.deepseek import parse_deepseek
from techbookocr.models.markdown import blocks_to_markdown

RAW = (
    "<|ref|>title<|/ref|><|det|>[[0, 0, 999, 99]]<|/det|>\n# Атлас дефектов\n\n"
    "<|ref|>text<|/ref|><|det|>[[0, 100, 999, 500]]<|/det|>\nТекст абзаца.\n\n"
    "<|ref|>equation<|/ref|><|det|>[[0,500,999,600]]<|/det|>\n\\[ x = 1 \\]\n"
    "<|ref|>image<|/ref|><|det|>[[0,600,999,900]]<|/det|>\n"
    "<｜end▁of▁sentence｜>"
)


def test_parse_deepseek():
    blocks = parse_deepseek(RAW, (1998, 2997))
    assert [b.category for b in blocks] == ["Title", "Text", "Formula", "Picture"]
    assert blocks[0].bbox == (0, 0, 1998, 297)
    assert blocks[1].text == "Текст абзаца."
    assert "end" not in blocks[3].text


def test_markdown():
    md = blocks_to_markdown(parse_deepseek(RAW, (1998, 2997)))
    assert md.startswith("# Атлас дефектов\n\nТекст абзаца.\n\n$$\nx = 1\n$$")


def test_no_grounding_tags():
    blocks = parse_deepseek("Просто текст<｜end▁of▁sentence｜>", (10, 10))
    assert [(b.category, b.text) for b in blocks] == [("Text", "Просто текст")]


def test_garbled_coordinates():
    """Parsers must never raise on odd model output - degrade gracefully."""
    # inf values
    blocks = parse_deepseek("<|ref|>text<|/ref|><|det|>[[0, 0, inf]]<|/det|>\nText", (100, 100))
    assert len(blocks) == 1
    assert blocks[0].bbox is None

    # Scientific notation that overflows (1e999)
    blocks = parse_deepseek("<|ref|>text<|/ref|><|det|>[[0, 0, 1e999, 5]]<|/det|>\nText", (100, 100))
    assert len(blocks) == 1
    assert blocks[0].bbox is None

    # Missing coordinates
    blocks = parse_deepseek("<|ref|>text<|/ref|><|det|>[[a,b]]<|/det|>\nText", (100, 100))
    assert len(blocks) == 1
    assert blocks[0].bbox is None

    # Empty coordinates
    blocks = parse_deepseek("<|ref|>text<|/ref|><|det|>[]<|/det|>\nText", (100, 100))
    assert len(blocks) == 1
    assert blocks[0].bbox is None


def test_deepseek_bbox_clamped_and_inverted_dropped():
    from techbookocr.models.adapters.deepseek import parse_deepseek

    raw = "<|ref|>text<|/ref|><|det|>[[-10, 0, 2000, 500]]<|/det|>A\n<|ref|>text<|/ref|><|det|>[[500, 500, 100, 100]]<|/det|>B"
    blocks = parse_deepseek(raw, (1000, 1000))
    assert blocks[0].bbox == (0, 0, 1000, 501) and blocks[1].bbox is None
