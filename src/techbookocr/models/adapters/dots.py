"""dots.mocr / dots.ocr: page layout as JSON blocks with bbox (rednote-hilab / dots-studio)."""
from __future__ import annotations

import json
import math
import re

from PIL import Image

from techbookocr.models.adapters.base import ChatAdapter
from techbookocr.models.markdown import blocks_to_markdown
from techbookocr.models.types import CATEGORIES, Block, clamp_bbox

# Verbatim from dots_mocr/utils/prompts.py ("prompt_layout_all_en")
PROMPT_LAYOUT_ALL_EN = """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text content within the bbox.

1. Bbox format: [x1, y1, x2, y2]

2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].

3. Text Extraction & Formatting Rules:
    - Picture: For the 'Picture' category, the text field should be omitted.
    - Formula: Format its text as LaTeX.
    - Table: Format its text as HTML.
    - All Others (Text, Title, etc.): Format their text as Markdown.

4. Constraints:
    - The output text must be the original text from the image, with no translation.
    - All layout elements must be sorted according to human reading order.

5. Final Output: The entire output must be a single JSON object.
"""
IMAGE_PREFIX = "<|img|><|imgpad|><|endofimg|>"  # without it vLLM v1 inserts "\n" (the official client)
MAX_PIXELS_SERVER = 11289600  # default of the reference client; the real server ceiling is set by server_max_pixels
DEFAULT_SERVER_MAX_PIXELS = 4_000_000  # --mm-processor-kwargs max_pixels in techbookocr.toml
_CELL = re.compile(
    r'\{\s*"bbox"\s*:\s*\[[^\]]*\]\s*,\s*"category"\s*:\s*"[^"]*"\s*(?:,\s*"text"\s*:\s*"(?:[^"\\]|\\.)*"\s*)?\}'
)


def _round(n: float, f: int) -> int:
    return round(n / f) * f


def _floor(n: float, f: int) -> int:
    return math.floor(n / f) * f


def _ceil(n: float, f: int) -> int:
    return math.ceil(n / f) * f


def smart_resize(height: int, width: int, factor: int = 28, min_pixels: int = 3136,
                 max_pixels: int = MAX_PIXELS_SERVER) -> tuple[int, int]:
    """Copy of qwen2-vl smart_resize from dots_mocr/utils/image_utils.py."""
    if max(height, width) / min(height, width) > 200:
        raise ValueError("absolute aspect ratio must be smaller than 200")
    h_bar = max(factor, _round(height, factor))
    w_bar = max(factor, _round(width, factor))
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(factor, _floor(height / beta, factor))
        w_bar = max(factor, _floor(width / beta, factor))
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = _ceil(height * beta, factor)
        w_bar = _ceil(width * beta, factor)
        if h_bar * w_bar > max_pixels:
            beta = math.sqrt((h_bar * w_bar) / max_pixels)
            h_bar = max(factor, _floor(h_bar / beta, factor))
            w_bar = max(factor, _floor(w_bar / beta, factor))
    return h_bar, w_bar


def fit_pixels(img: Image.Image, max_pixels: int) -> Image.Image:
    w, h = img.size
    if w * h <= max_pixels:
        return img
    s = math.sqrt(max_pixels / (w * h))
    return img.resize((int(w * s), int(h * s)), Image.Resampling.LANCZOS)


def _load_cells(raw: str) -> list[dict] | None:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            # If dict has "bbox" or "category", it's a single cell
            if "bbox" in data or "category" in data:
                data = [data]
            else:
                # Otherwise, find first value that is a list of dicts, else use dict as single cell
                data = next((v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [data])
        # Ensure data is a list and only keep dict items
        if isinstance(data, list):
            data = [c for c in data if isinstance(c, dict)]
            return data if data else None
        return None
    except json.JSONDecodeError:
        cells = []
        for m in _CELL.finditer(raw):
            try:
                cells.append(json.loads(m.group(0)))
            except json.JSONDecodeError:
                continue
        return cells or None


def parse_dots(raw: str, orig_size: tuple[int, int], sent_size: tuple[int, int],
               server_max_pixels: int = DEFAULT_SERVER_MAX_PIXELS) -> list[Block]:
    cells = _load_cells(raw)
    if cells is None:
        return [Block("Text", raw.strip())]
    ow, oh = orig_size
    try:
        h_bar, w_bar = smart_resize(sent_size[1], sent_size[0], max_pixels=server_max_pixels)
        sx, sy = w_bar / ow, h_bar / oh
    except ValueError:
        # If smart_resize fails (e.g., aspect ratio issue), use None for all bboxes
        h_bar, w_bar, sx, sy = None, None, None, None

    blocks = []
    for i, c in enumerate(cells):
        if not isinstance(c, dict):
            continue
        cat = c.get("category", "Text")
        text = c.get("text", "") or ""

        # Try to extract and validate bbox
        bbox = None
        if sx is not None and sy is not None:
            try:
                bbox_raw = c.get("bbox", [])
                if isinstance(bbox_raw, list) and len(bbox_raw) >= 4:
                    x1, y1, x2, y2 = (float(v) for v in bbox_raw[:4])
                    bbox = clamp_bbox((x1 / sx, y1 / sy, x2 / sx, y2 / sy), orig_size)
            except (ValueError, TypeError, OverflowError):
                bbox = None

        blocks.append(Block(cat if cat in CATEGORIES else "Text", text, bbox, i))
    return blocks


class DotsAdapter(ChatAdapter):
    # max_pixels is the client-side downscale target; server_max_pixels is the server ceiling (must match
    # --mm-processor-kwargs in techbookocr.toml), and smart_resize uses it to map bbox back.
    default_params = {"max_tokens": 24000, "max_pixels": 3_900_000, "server_max_pixels": DEFAULT_SERVER_MAX_PIXELS,
                      "temperature": 0.1, "extra": {"top_p": 0.9}}

    def __init__(self, spec, client, base_url):
        super().__init__(spec, client, base_url)
        if self.params["max_pixels"] >= self.params["server_max_pixels"]:
            raise ValueError(f"{spec.key}: params.max_pixels ({self.params['max_pixels']}) must be below "
                             f"server_max_pixels ({self.params['server_max_pixels']})")

    def prepare(self, image: Image.Image) -> Image.Image:
        return fit_pixels(image, self.params["max_pixels"])

    def prompt(self) -> str:
        return IMAGE_PREFIX + PROMPT_LAYOUT_ALL_EN

    def parse(self, raw, orig_size, sent_size):
        blocks = parse_dots(raw, orig_size, sent_size, self.params["server_max_pixels"])
        return blocks, blocks_to_markdown(blocks)
