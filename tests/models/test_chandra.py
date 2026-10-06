from PIL import Image

from techbookocr.models.adapters.chandra import OCR_LAYOUT_PROMPT, html_to_md, parse_chandra, scale_to_fit
from techbookocr.models.markdown import blocks_to_markdown

RAW = (
    '<div data-bbox="0 0 500 100" data-label="Section-Header"><h2>Методы анализа</h2></div>'
    '<div data-bbox="0 100 1000 400" data-label="Text"><p>Доля графита <math>W_г</math> равна 2,2.</p><p>Второй абзац.</p></div>'
    '<div data-bbox="0 400 1000 600" data-label="Table"><table><tr><td colspan="2">A &amp; B</td></tr></table></div>'
    '<div data-bbox="0 600 1000 700" data-label="Equation-Block"><math display="block">m_г &lt; 1</math></div>'
    '<div data-bbox="0 700 1000 900" data-label="Image"><img alt="микрофото"/>Описание снимка</div>'
    '<div data-bbox="0 950 1000 1000" data-label="Page-Footer"><p>41</p></div>'
)


def test_parse_categories_and_bbox():
    blocks = parse_chandra(RAW, (2000, 3000))
    assert [b.category for b in blocks] == ["Section-header", "Text", "Table", "Formula", "Picture", "Page-footer"]
    assert blocks[0].bbox == (0, 0, 1000, 300)
    assert blocks[1].text == "Доля графита $W_г$ равна 2,2.\n\nВторой абзац."
    assert blocks[2].text.startswith("<table>") and 'colspan="2"' in blocks[2].text and "A &amp; B" in blocks[2].text
    assert blocks[3].text == "$$m_г < 1$$"
    assert blocks[4].text == ""


def test_markdown_from_chandra():
    md = blocks_to_markdown(parse_chandra(RAW, (2000, 3000)))
    assert md.startswith("## Методы анализа\n\n")
    assert "$$\nm_г < 1\n$$" in md
    assert "41" not in md


def test_list_group():
    assert html_to_md("<ul><li>первый</li><li>второй</li></ul>") == "- первый\n\n- второй"


def test_plain_text_output_is_kept():
    blocks = parse_chandra("Просто текст без разметки", (100, 100))
    assert [(b.category, b.text) for b in blocks] == [("Text", "Просто текст без разметки")]


def test_scale_to_fit_grid():
    img = scale_to_fit(Image.new("RGB", (2500, 3500)))
    w, h = img.size
    assert w % 28 == 0 and h % 28 == 0 and w * h <= 3072 * 2048


def test_prompt_verbatim_parts():
    assert "Bboxes are normalized 0-1000." in OCR_LAYOUT_PROMPT
    assert "Only use these tags ['math', 'br', 'i'," in OCR_LAYOUT_PROMPT


# Fix round 1 tests
def test_overflow_error_in_bbox():
    """Issue 1: OverflowError in bbox parsing with inf/1e999 should not escape."""
    # Should not raise, should set bbox=None
    blocks = parse_chandra('<div data-bbox="inf 0 5 5" data-label="Text">content</div>', (100, 100))
    assert blocks[0].bbox is None

    blocks = parse_chandra('<div data-bbox="1e999 0 5 5" data-label="Text">content</div>', (100, 100))
    assert blocks[0].bbox is None


def test_missing_bbox_returns_none():
    """Issue 1: Missing data-bbox should set bbox=None, not (0,0,0,0)."""
    blocks = parse_chandra('<div data-label="Text">content</div>', (100, 100))
    assert blocks[0].bbox is None


def test_text_with_entities_not_double_unescaped():
    """Issue 2: Text with entities should not be double-unescaped."""
    blocks = parse_chandra('<div data-label="Text">x &lt; y and z &gt; w</div>', (100, 100))
    # Should be "x < y and z > w", not "x  w"
    assert blocks[0].text == "x < y and z > w"


def test_table_in_text_block_with_surrounding():
    """Issue 3: Complex-Block with table should keep table HTML inline."""
    raw = '<div data-label="Complex-Block"><p>intro</p><table><tr><td>a</td><td>b</td></tr></table><p>after</p></div>'
    blocks = parse_chandra(raw, (100, 100))
    # Text should have intro, HTML table, after joined with \n\n
    assert blocks[0].category == "Text"
    assert "intro" in blocks[0].text
    assert "<table>" in blocks[0].text
    assert "<tr>" in blocks[0].text
    assert "<td>a</td><td>b</td>" in blocks[0].text
    assert "after" in blocks[0].text
    assert blocks[0].text == 'intro\n\n<table><tr><td>a</td><td>b</td></tr></table>\n\nafter'


def test_table_block_with_caption():
    """Issue 3: Table block with caption <p> before table should include caption."""
    raw = '<div data-label="Table"><p>Table caption</p><table><tr><td>a</td></tr></table></div>'
    blocks = parse_chandra(raw, (100, 100))
    assert blocks[0].category == "Table"
    # Should have caption text before the table
    assert "Table caption" in blocks[0].text
    assert "<table>" in blocks[0].text


def test_all_blank_page_returns_empty_list():
    """Issue 4: All-Blank-Page response should return [], not fallback Text block."""
    raw = '<div data-label="Blank-Page"></div>'
    blocks = parse_chandra(raw, (100, 100))
    assert blocks == []


def test_fallback_text_only_when_no_data_labels():
    """Issue 4: Fallback Text block only when raw has no data-label elements."""
    # With data-label elements but all filtered → []
    raw = '<div data-label="Blank-Page"></div><div data-label="Blank-Page"></div>'
    blocks = parse_chandra(raw, (100, 100))
    assert blocks == []

    # No data-label elements at all → fallback Text block
    raw = 'just plain text'
    blocks = parse_chandra(raw, (100, 100))
    assert len(blocks) == 1
    assert blocks[0].category == "Text"
    assert blocks[0].text == "just plain text"


# Fix round 2 tests
def test_tail_text_after_table_is_kept():
    """Fix 3: Tail text after a table should not be dropped."""
    raw = '<div data-label="Text">intro<table><tr><td>a</td></tr></table>tail text</div>'
    blocks = parse_chandra(raw, (100, 100))
    # Should include: intro, table, tail text
    assert "intro" in blocks[0].text
    assert "<table>" in blocks[0].text
    assert "tail text" in blocks[0].text
    assert blocks[0].text == 'intro\n\n<table><tr><td>a</td></tr></table>\n\ntail text'


def test_two_tables_in_text_block():
    """Fix 3: Two tables in a Text block should both be kept as HTML."""
    raw = '<div data-label="Text"><p>start</p><table><tr><td>table1</td></tr></table><p>middle</p><table><tr><td>table2</td></tr></table><p>end</p></div>'
    blocks = parse_chandra(raw, (100, 100))
    text = blocks[0].text
    # Should have both tables as HTML
    assert text.count("<table>") == 2
    assert "table1" in text
    assert "table2" in text
    # Should have text: start, middle, end
    assert "start" in text
    assert "middle" in text
    assert "end" in text


def test_table_block_with_caption_and_tail():
    """Fix 3: Table block with caption, table, and tail text should keep all."""
    raw = '<div data-label="Table"><p>caption</p><table><tr><td>data</td></tr></table><p>footer</p></div>'
    blocks = parse_chandra(raw, (100, 100))
    text = blocks[0].text
    assert blocks[0].category == "Table"
    # Should have caption, table, and footer
    assert "caption" in text
    assert "<table>" in text
    assert "footer" in text


def test_two_tables_in_table_block():
    """Fix 3: Table block with two tables should keep both."""
    raw = '<div data-label="Table"><table><tr><td>a</td></tr></table><table><tr><td>b</td></tr></table></div>'
    blocks = parse_chandra(raw, (100, 100))
    text = blocks[0].text
    assert blocks[0].category == "Table"
    # Should have both tables
    assert text.count("<table>") == 2
    assert "a" in text
    assert "b" in text


# Fix round 3 tests
def test_table_nested_in_div_in_text_block():
    """Fix 4: Table nested inside a div inside Text block should be preserved as HTML."""
    raw = '<div data-label="Text"><p>a</p><div><table><tr><td>x</td></tr></table>b</div></div>'
    blocks = parse_chandra(raw, (100, 100))
    text = blocks[0].text
    assert blocks[0].category == "Text"
    # Should have: 'a', table HTML, and 'b'
    assert "a" in text
    assert "<table>" in text
    assert "<td>x</td>" in text
    assert "b" in text
    assert text == 'a\n\n<table><tr><td>x</td></tr></table>\n\nb'


def test_table_nested_in_div_in_table_block():
    """Fix 4: Table nested inside a div inside Table block should be preserved as HTML."""
    raw = '<div data-label="Table"><div><table><tr><td>x</td></tr></table></div></div>'
    blocks = parse_chandra(raw, (100, 100))
    text = blocks[0].text
    assert blocks[0].category == "Table"
    # Should have table HTML
    assert "<table>" in text
    assert "<td>x</td>" in text


def test_chandra_bbox_clamped_and_inverted_dropped():
    from techbookocr.models.adapters.chandra import parse_chandra

    raw = ('<div data-bbox="-100 0 2000 500" data-label="Text"><p>A</p></div>'
           '<div data-bbox="500 500 100 100" data-label="Text"><p>B</p></div>')
    blocks = parse_chandra(raw, (1000, 1000))
    assert blocks[0].bbox == (0, 0, 1000, 500) and blocks[1].bbox is None
