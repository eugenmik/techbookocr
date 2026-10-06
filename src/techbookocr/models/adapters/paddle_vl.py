"""PaddleOCR-VL-1.6: PP-DocLayoutV3 detector (CPU, separate worker) + crop recognition on vLLM."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from PIL import Image

from techbookocr.config import ModelSpec
from techbookocr.models.errors import ERR_PARSE
from techbookocr.models.markdown import blocks_to_markdown
from techbookocr.models.types import Block, PageResult, clamp_bbox
from techbookocr.models.worker import JsonLineWorker

WORKER = Path(__file__).with_name("paddle_worker.py")
_LABELS = {
    "doc_title": "Title", "paragraph_title": "Section-header", "text": "Text", "content": "Text",
    "abstract": "Text", "reference": "Text", "reference_content": "Text", "aside_text": "Text",
    "table": "Table", "display_formula": "Formula", "formula": "Formula", "inline_formula": "Formula",
    "image": "Picture", "chart": "Picture", "figure": "Picture", "seal": "Picture",
    "figure_title": "Caption", "table_title": "Caption", "chart_title": "Caption", "vision_footnote": "Footnote",
    "footnote": "Footnote", "header": "Page-header", "header_image": "Page-header", "footer": "Page-footer",
    "footer_image": "Page-footer", "number": "Page-footer", "formula_number": "Text", "algorithm": "Text",
}


def blocks_from_paddle(items: list[dict], size: tuple[int, int]) -> list[Block]:
    """Convert paddle items to blocks; never raises on odd items (they degrade or are skipped)."""
    blocks: list[Block] = []
    for it in items if isinstance(items, (list, tuple)) else []:
        if not isinstance(it, dict):
            continue
        try:
            label = it.get("label", "")
            cat = _LABELS.get(label, "Text") if isinstance(label, str) else "Text"
            bbox = None
            try:
                raw = it.get("bbox")
                if isinstance(raw, (list, tuple)) and len(raw) >= 4:
                    bbox = clamp_bbox(raw, size)
            except Exception:  # noqa: BLE001 — inf/NaN/str/etc.: bbox degrades to None
                bbox = None
            content = it.get("content")
            if content is None:
                content = ""
            elif not isinstance(content, str):
                content = str(content)
            blocks.append(Block(cat, "" if cat == "Picture" else content, bbox, len(blocks)))
        except Exception:  # noqa: BLE001
            continue
    return blocks


class PaddleVLAdapter(JsonLineWorker):
    label = "paddle worker"

    def __init__(self, spec: ModelSpec, client, base_url: str, worker_cmd: list[str] | None = None,
                 startup_timeout: float = 1800.0, page_timeout: float = 600.0, stderr_path: Path | None = None):
        self.spec, self.name, self.base_url = spec, spec.key, base_url
        super().__init__(worker_cmd or [
            "uv", "run", "--no-project", "--python", "3.12",
            "--with", "paddlepaddle==3.2.1", "--with", "paddleocr[doc-parser]==3.7.0", "--with", "safetensors",
            "python", str(WORKER), base_url, spec.model,
        ], startup_timeout, page_timeout, stderr_path or Path(tempfile.gettempdir()) / "techbookocr-paddle-worker.log")

    def ocr_page(self, image: Image.Image) -> PageResult:
        """A page; never hangs. Worker failures (died, timeout, not ready) are TransportError and the worker
        restarts on the next call; content failures are PageResult.error."""
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.png"
            image.save(path)
            msg = self.request({"image": str(path)})
        raw = json.dumps(msg, ensure_ascii=False)
        if msg.get("error") is not None:
            return PageResult(markdown="", raw=raw, seconds=time.monotonic() - t0, error=str(msg["error"]))
        if not isinstance(msg.get("blocks"), list):
            return PageResult(markdown="", raw=raw, seconds=time.monotonic() - t0,
                              error=f"{ERR_PARSE}: paddle worker malformed reply (no blocks)")
        blocks = blocks_from_paddle(msg["blocks"], image.size)
        return PageResult(markdown=blocks_to_markdown(blocks), blocks=blocks, raw=raw, seconds=time.monotonic() - t0)
