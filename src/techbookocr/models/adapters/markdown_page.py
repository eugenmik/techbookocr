"""Models that return page Markdown without bbox: HunyuanOCR 1.5 and Qwen3.5-9B."""
from __future__ import annotations

import re

from PIL import Image

from techbookocr.models.adapters.base import ChatAdapter

# Verbatim from HunyuanOCR inference/utils/tasks.py ("doc_parse"); prompts are fixed, edits degrade quality
HUNYUAN_DOC_PARSE = "提取文档图片中正文的所有信息用markdown格式表示，其中页眉、页脚部分忽略，表格用html格式表达，文档中公式用latex格式表示，按照阅读顺序组织进行解析。"

# Verbatim from inference/utils/tasks.py: structured_parse, formula, table
HUNYUAN_STRUCTURED = "提取图中的文字。"
HUNYUAN_FORMULA = "识别图片中的公式，用LaTeX格式表示。"
HUNYUAN_TABLE = "把图中的表格解析为HTML。"

QWEN_PAGE_PROMPT = """Convert this scanned book page to Markdown.
Rules:
- Transcribe the text exactly as printed, in the original language (Russian, English or German). Do not translate, correct or summarize.
- Skip running headers and page numbers.
- Headings as Markdown headings; lists as Markdown lists; join hyphenated line breaks.
- Tables as HTML <table> with rowspan/colspan matching the printed structure; keep every number exactly.
- Formulas in LaTeX: inline $...$, display $$...$$.
- Figures as ![]() followed by the caption text as a separate paragraph.
Output only the Markdown."""

_FENCE = re.compile(r"^```(?:markdown|md)?\s*\n(.*?)\n?```\s*$", re.S)
_COORDS = re.compile(r"\s*\(\d+,\s*\d+\),\s*\(\d+,\s*\d+\)[ \t]*$", re.M)


def clean_markdown(raw: str) -> str:
    text = raw.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    text = _COORDS.sub("", text).strip()
    return text + "\n" if text else ""


def fit_side(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    s = max_side / max(w, h)
    return img.resize((int(w * s), int(h * s)), Image.Resampling.LANCZOS)


class HunyuanAdapter(ChatAdapter):
    system = ""  # the official client sends an empty system message
    default_params = {"max_tokens": 16000, "block_max_tokens": 4096, "max_side": 2560, "temperature": 0.0,
                      "retry_temperatures": [],
                      "extra": {"top_p": 1.0, "top_k": -1, "repetition_penalty": 1.08, "skip_special_tokens": True}}

    def prepare(self, image):
        return fit_side(image, self.params["max_side"])

    def prompt(self):
        return HUNYUAN_DOC_PARSE

    def parse(self, raw, orig_size, sent_size):
        return [], clean_markdown(raw)

    def block_prompt(self, kind):
        return {"formula": HUNYUAN_FORMULA, "table": HUNYUAN_TABLE, "page": HUNYUAN_DOC_PARSE}.get(
            kind, HUNYUAN_STRUCTURED)

    def block_max_tokens(self, kind):
        return self.params["max_tokens"] if kind == "page" else self.params["block_max_tokens"]

    def parse_block(self, raw, kind):
        return clean_markdown(raw).strip()


class QwenPageAdapter(ChatAdapter):
    default_params = {"max_tokens": 10000, "temperature": 0.0,
                      "extra": {"chat_template_kwargs": {"enable_thinking": False}}}

    def prompt(self):
        return QWEN_PAGE_PROMPT

    def parse(self, raw, orig_size, sent_size):
        return [], clean_markdown(raw)
