"""DeepSeek-OCR 2: grounding markup <|ref|>...<|det|>[[...]] with coordinates 0-999."""
from __future__ import annotations

import ast
import re

from techbookocr.models.adapters.base import ChatAdapter
from techbookocr.models.markdown import blocks_to_markdown
from techbookocr.models.types import Block, clamp_bbox

PROMPT = "<|grounding|>Convert the document to markdown."
_REF = re.compile(r"<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>", re.S)
_SPECIAL = re.compile(r"<｜[^｜]*｜>|<\|[^|]*\|>")
_LABELS = {
    "title": "Title", "sub_title": "Section-header", "text": "Text", "table": "Table", "image": "Picture",
    "figure": "Picture", "image_caption": "Caption", "table_caption": "Caption", "equation": "Formula",
    "formula": "Formula", "list": "List-item", "header": "Page-header", "footer": "Page-footer",
    "page_footnote": "Footnote", "footnote": "Footnote", "table_footnote": "Footnote",
}


def _clean(text: str) -> str:
    return _SPECIAL.sub("", text).strip()


def parse_deepseek(raw: str, orig_size: tuple[int, int]) -> list[Block]:
    w, h = orig_size
    matches = list(_REF.finditer(raw))
    if not matches:
        text = _clean(raw)
        return [Block("Text", text, None, 0)] if text else []
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        content = _clean(raw[m.end():end])
        bbox = None
        try:
            coords = ast.literal_eval(m.group(2).strip())
            if coords:  # Check if list is not empty
                x1, y1, x2, y2 = coords[0][:4]
                bbox = clamp_bbox((x1 * w / 999, y1 * h / 999, x2 * w / 999, y2 * h / 999), (w, h))
        except Exception:
            # Degrade gracefully on garbled coordinates (OverflowError, ValueError, SyntaxError, IndexError, TypeError, etc.)
            bbox = None
        cat = _LABELS.get(m.group(1).strip().lower(), "Text")
        blocks.append(Block(cat, "" if cat == "Picture" else content, bbox, i))
    return blocks


class DeepseekAdapter(ChatAdapter):
    default_params = {
        "max_tokens": 7000, "temperature": 0.0, "retry_temperatures": [],
        "extra": {"skip_special_tokens": False,
                  "vllm_xargs": {"ngram_size": 30, "window_size": 90, "whitelist_token_ids": [128821, 128822]}},
    }

    def prompt(self):
        return PROMPT

    def parse(self, raw, orig_size, sent_size):
        blocks = parse_deepseek(raw, orig_size)
        return blocks, blocks_to_markdown(blocks)
