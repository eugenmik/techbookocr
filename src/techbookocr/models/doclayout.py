"""PP-DocLayoutV3 in a separate uv environment: layout regions on an image (a table crop).

device='gpu' installs paddlepaddle-gpu instead of paddlepaddle, so the detector runs on the GPU
(the sketches stage runs while OCR models are unloaded, so there is no VRAM conflict)."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from techbookocr.models.errors import ERR_PARSE
from techbookocr.models.types import clamp_bbox
from techbookocr.models.worker import JsonLineWorker

WORKER = Path(__file__).with_name("doclayout_worker.py")


@dataclass(frozen=True)
class Region:
    label: str
    score: float
    bbox: tuple[int, int, int, int]


class DocLayoutDetector(JsonLineWorker):
    label = "doclayout worker"

    def __init__(self, worker_cmd: list[str] | None = None, startup_timeout: float = 1800.0, timeout: float = 300.0,
                 stderr_path: Path | None = None, threshold: float = 0.2, device: str = "cpu"):
        if device not in ("cpu", "gpu"):
            raise ValueError(f"device must be 'cpu' or 'gpu', got {device!r}")
        self.name = "pp-doclayoutv3"
        cmd = ["uv", "run", "--no-project", "--python", "3.12"]
        if device == "gpu":
            # paddlepaddle-gpu was removed from PyPI after 2.6.x; 3.x GPU builds live on the paddle index;
            # unsafe-best-match: otherwise paddleocr is taken only from the paddle index, which has an old version
            cmd += ["--index", "https://www.paddlepaddle.org.cn/packages/stable/cu126/",
                    "--index-strategy", "unsafe-best-match"]
        cmd += ["--with", "paddlepaddle-gpu==3.2.1" if device == "gpu" else "paddlepaddle==3.2.1",
                "--with", "paddleocr[doc-parser]==3.7.0", "--with", "safetensors",
                "python", str(WORKER), str(threshold), device]
        super().__init__(worker_cmd or cmd, startup_timeout, timeout,
                         stderr_path or Path(tempfile.gettempdir()) / "techbookocr-doclayout-worker.log")

    def detect(self, image: Image.Image) -> tuple[list[Region], str | None]:
        """Regions in image pixels. TransportError is a worker failure; ([], error) is a content failure."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crop.png"
            image.save(path)
            msg = self.request({"image": str(path)})
        if msg.get("error") is not None:
            return [], str(msg["error"])
        boxes = msg.get("boxes")
        if not isinstance(boxes, list):
            return [], f"{ERR_PARSE}: doclayout worker malformed reply (no boxes)"
        regions = []
        for b in boxes:
            if not isinstance(b, dict) or not isinstance(b.get("label"), str):
                continue
            score, raw = b.get("score"), b.get("bbox")
            if not isinstance(score, (int, float)) or not isinstance(raw, (list, tuple)):
                continue
            bbox = clamp_bbox(raw, image.size)
            if bbox is not None:
                regions.append(Region(b["label"], float(score), bbox))
        return regions, None
