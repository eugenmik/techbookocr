"""Chandra OCR 2 (datalab-to): HTML blocks <div data-bbox data-label>, bbox 0-1000."""
from __future__ import annotations

import html
import math
import re

from lxml import html as lhtml
from PIL import Image

from techbookocr.models.adapters.base import ChatAdapter
from techbookocr.models.errors import ERR_PARSE
from techbookocr.models.markdown import blocks_to_markdown
from techbookocr.models.types import Block, BlockResult, clamp_bbox

# Verbatim from chandra/prompts.py
ALLOWED_TAGS = ["math", "br", "i", "b", "u", "del", "sup", "sub", "table", "tr", "td", "p", "th", "div", "pre",
                "h1", "h2", "h3", "h4", "h5", "ul", "ol", "li", "input", "a", "span", "img", "hr", "tbody",
                "small", "caption", "strong", "thead", "big", "code", "chem"]
ALLOWED_ATTRIBUTES = ["class", "colspan", "rowspan", "display", "checked", "type", "border", "value", "style",
                      "href", "alt", "align", "data-bbox", "data-label"]
PROMPT_ENDING = f"""
Only use these tags {ALLOWED_TAGS}, and these attributes {ALLOWED_ATTRIBUTES}.

Guidelines:
* Inline math: Surround math with <math>...</math> tags. Math expressions should be rendered in KaTeX-compatible LaTeX. Use display for block math.
* Tables: Use colspan and rowspan attributes to match table structure.
* Formatting: Maintain consistent formatting with the image, including spacing, indentation, subscripts/superscripts, and special characters.
* Images: Include a description of any images in the alt attribute of an <img> tag. Do not fill out the src property. Describe in detail inside the div tag. Also convert charts to high fidelity data, and convert diagrams to mermaid.
* Forms: Mark checkboxes and radio buttons properly.
* Text: join lines together properly into paragraphs using <p>...</p> tags.  Use <br> tags for line breaks within paragraphs, but only when absolutely necessary to maintain meaning.
* Chemistry: Use <chem>...</chem> tags for chemical formulas with reactive SMILES.
* Lists: Preserve indents and proper list markers.
* Use the simplest possible HTML structure that accurately represents the content of the block.
* Make sure the text is accurate and easy for a human to read and interpret.  Reading order should be correct and natural.
""".strip()
OCR_LAYOUT_PROMPT = f"""
OCR this image to HTML, arranged as layout blocks.  Each layout block should be a div with the data-bbox attribute representing the bounding box of the block in x0 y0 x1 y1 format.  Bboxes are normalized 0-1000. The data-label attribute is the label for the block.

Use the following labels:
- Caption
- Footnote
- Equation-Block
- List-Group
- Page-Header
- Page-Footer
- Image
- Section-Header
- Table
- Text
- Complex-Block
- Code-Block
- Form
- Table-Of-Contents
- Figure
- Chemical-Block
- Diagram
- Bibliography
- Blank-Page

{PROMPT_ENDING}
""".strip()
OCR_PROMPT = f"""
OCR this image to HTML.

{PROMPT_ENDING}
""".strip()

TABLE_HINT = ("The image contains a table. Output it as one <table> element, using colspan and rowspan "
              "to match the table structure; keep every number and dash.")
TABLE_PROMPT = f"{OCR_PROMPT}\n\n{TABLE_HINT}"

_LABELS: dict[str, str | None] = {
    "Caption": "Caption", "Footnote": "Footnote", "Equation-Block": "Formula", "List-Group": "List-item",
    "Page-Header": "Page-header", "Page-Footer": "Page-footer", "Image": "Picture", "Figure": "Picture",
    "Diagram": "Picture", "Section-Header": "Section-header", "Table": "Table", "Text": "Text",
    "Complex-Block": "Text", "Code-Block": "Text", "Form": "Text", "Table-Of-Contents": "Text",
    "Chemical-Block": "Formula", "Bibliography": "Text", "Blank-Page": None,
}


def html_to_md(fragment: str) -> str:
    s = re.sub(r"<math\b[^>]*\bdisplay\b[^>]*>(.*?)</math>", lambda m: f"$${m.group(1).strip()}$$", fragment, flags=re.S)
    s = re.sub(r"<math\b[^>]*>(.*?)</math>", lambda m: f"${m.group(1).strip()}$", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<li\b[^>]*>", "\n\n- ", s)
    s = re.sub(r"</(p|li|h[1-6]|div|ul|ol)>", "\n\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


_MATH_TAG = re.compile(r"<math\b[^>]*>(.*?)</math>", re.S)


def table_html(raw: str) -> str:
    """First <table> of a Chandra reply: <math> -> $...$, <img> attributes stripped (alt descriptions are invented by the model).

    Empty <img> tags remain as sketch placeholders for assemble.fill_sketches. ValueError if there is no table."""
    doc = lhtml.fragment_fromstring(raw, create_parent="div")
    table = doc.find(".//table")
    if table is None:
        raise ValueError("no <table> in output")
    for img in table.iter("img"):
        img.attrib.clear()
    out = lhtml.tostring(table, encoding="unicode", with_tail=False)
    return _MATH_TAG.sub(lambda m: f"${m.group(1).strip()}$", out)


def _inner_html(el) -> str:
    """Get inner HTML, escaping direct text to prevent double-unescaping."""
    return html.escape(el.text or "") + "".join(lhtml.tostring(c, encoding="unicode") for c in el)


def _block_content(el) -> str:
    """Walk block content in document order, preserving tables as HTML and converting other content to text.

    Returns a string with non-table content converted to markdown and table elements kept as HTML,
    joined by double newlines. Properly handles tail text after tables.
    """
    parts = []
    html_buffer = ""

    # Start with element's direct text
    if el.text:
        html_buffer += html.escape(el.text)

    # Walk direct children
    for child in el:
        if child.tag == "table":
            # Flush accumulated HTML to markdown
            if html_buffer.strip():
                md_part = html_to_md(html_buffer)
                if md_part.strip():
                    parts.append(md_part)
                html_buffer = ""

            # Append table as HTML (without tail, we'll handle it separately)
            table_html = lhtml.tostring(child, encoding="unicode", with_tail=False)
            parts.append(table_html)

            # Process tail text after the table
            if child.tail:
                html_buffer = html.escape(child.tail)
        else:
            # Non-table child: check if it contains a table
            if next(child.iter("table"), None) is not None:
                # Child contains a table: flush buffer, recurse, handle tail
                if html_buffer.strip():
                    md_part = html_to_md(html_buffer)
                    if md_part.strip():
                        parts.append(md_part)
                    html_buffer = ""

                # Recursively process child to preserve nested table
                child_content = _block_content(child)
                if child_content.strip():
                    parts.append(child_content)

                # Process tail text after the child
                if child.tail:
                    html_buffer = html.escape(child.tail)
            else:
                # Child has no table: serialize normally
                child_html = lhtml.tostring(child, encoding="unicode", with_tail=False)
                html_buffer += child_html
                if child.tail:
                    html_buffer += html.escape(child.tail)

    # Flush remaining HTML buffer
    if html_buffer.strip():
        md_part = html_to_md(html_buffer)
        if md_part.strip():
            parts.append(md_part)

    return "\n\n".join(p for p in parts if p.strip())


def parse_chandra(raw: str, orig_size: tuple[int, int]) -> list[Block]:
    w, h = orig_size
    try:
        frags = lhtml.fragments_fromstring(raw)
    except Exception:
        frags = []
    blocks: list[Block] = []
    for el in frags:
        if isinstance(el, str) or el.get("data-label") is None:
            text = el if isinstance(el, str) else html_to_md(lhtml.tostring(el, encoding="unicode"))
            if text.strip():
                blocks.append(Block("Text", text.strip(), None, len(blocks)))
            continue
        cat = _LABELS.get(el.get("data-label"), "Text")
        if cat is None:
            continue
        bbox = None
        bbox_str = el.get("data-bbox", "").strip()
        if bbox_str:
            try:
                vals = bbox_str.split()[:4]
                if len(vals) == 4:
                    x0, y0, x1, y1 = (float(v) for v in vals)
                    bbox = clamp_bbox((x0 * w / 1000, y0 * h / 1000, x1 * w / 1000, y1 * h / 1000), (w, h))
            except (ValueError, OverflowError):
                bbox = None
        if cat == "Picture":
            text = ""
        elif cat == "Formula":
            # Formula: just convert to Markdown (may contain <math> tags)
            text = html_to_md(_inner_html(el))
        else:
            # For Table and Text-like categories, use _block_content to handle tables, captions, and tail text
            text = _block_content(el)
        blocks.append(Block(cat, text, bbox, len(blocks)))

    # Only add fallback Text block if no data-label elements were found at all
    if not blocks and raw.strip():
        # Check if there were any data-label elements
        has_labels = 'data-label' in raw
        if not has_labels:
            blocks.append(Block("Text", html_to_md(raw), None, 0))
    return blocks


def scale_to_fit(img: Image.Image, max_pixels: int = 3072 * 2048, grid: int = 28) -> Image.Image:
    w, h = img.size
    s = min(1.0, math.sqrt(max_pixels / (w * h)))
    nw, nh = max(grid, int(w * s) // grid * grid), max(grid, int(h * s) // grid * grid)
    return img if (nw, nh) == (w, h) else img.resize((nw, nh), Image.Resampling.LANCZOS)


class ChandraAdapter(ChatAdapter):
    default_params = {"max_tokens": 11000, "block_max_tokens": 8192, "temperature": 0.0, "extra": {"top_p": 0.1},
                      "retry_temperatures": [0.2, 0.4], "retry_extra": {"top_p": 0.95}}

    def prepare(self, image):
        return scale_to_fit(image)

    def prompt(self):
        return OCR_LAYOUT_PROMPT

    def parse(self, raw, orig_size, sent_size):
        blocks = parse_chandra(raw, orig_size)
        return blocks, blocks_to_markdown(blocks)

    def block_prompt(self, kind):
        # table_hint (params): for tables, add a note to the ocr prompt that the image is a table
        return TABLE_PROMPT if kind == "table" and self.params.get("table_hint") else OCR_PROMPT

    def parse_block(self, raw, kind):
        return table_html(raw) if kind == "table" else html_to_md(raw)

    def ocr_block(self, image, kind):
        """Table without <table> in the reply: one retry with the ocr_layout prompt (the table is taken from the Table div);
        raw replies are saved in raw so the failure can be analysed."""
        res = super().ocr_block(image, kind)
        if kind != "table" or not res.error or not res.error.startswith(ERR_PARSE) or "no <table>" not in res.error:
            return res
        retry = self.ask(image, OCR_LAYOUT_PROMPT, max_tokens=self.block_max_tokens(kind))
        raw = f"{res.raw}\n<!-- retry: ocr_layout -->\n{retry.raw}"
        seconds = res.seconds + retry.seconds
        if retry.error and not retry.text:
            return BlockResult("", raw, seconds, f"{res.error}; retry: {retry.error}")
        try:
            return BlockResult(table_html(retry.raw), raw, seconds, retry.error)
        except Exception as e:  # noqa: BLE001 — the retry also has no table: the first attempt's error, raw saved
            return BlockResult("", raw, seconds, f"{res.error}; retry: {type(e).__name__}: {e}")
