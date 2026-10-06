import sys

import pytest
from PIL import Image

from techbookocr.models.doclayout import DocLayoutDetector, Region
from techbookocr.models.errors import TransportError

READY = 'import json,sys\nprint("paddle noise")\nprint(json.dumps({"ready": True}),flush=True)\n'


def _det(tmp_path, body, **kw):
    script = tmp_path / "w.py"
    script.write_text(READY + body, encoding="utf-8")
    return DocLayoutDetector(worker_cmd=[sys.executable, str(script)], stderr_path=tmp_path / "w.log", **kw)


def test_detect_regions(tmp_path):
    det = _det(tmp_path, 'for l in sys.stdin:\n'
               '    print(json.dumps({"boxes": [{"label": "image", "score": 0.9, "bbox": [10, 20, 60, 80]},'
               '{"label": "text", "score": 0.8, "bbox": [-5, 0, 500, 30]}, {"label": 5}, "junk"]}), flush=True)\n')
    try:
        regions, err = det.detect(Image.new("RGB", (100, 100), "white"))
    finally:
        det.close()
    assert err is None
    assert regions == [Region("image", 0.9, (10, 20, 60, 80)), Region("text", 0.8, (0, 0, 100, 30))]


def test_detect_content_errors(tmp_path):
    det = _det(tmp_path, 'for i, l in enumerate(sys.stdin):\n'
               '    print(json.dumps({"error": "boom"} if i == 0 else {"weird": 1}), flush=True)\n')
    try:
        assert det.detect(Image.new("RGB", (8, 8))) == ([], "boom")
        regions, err = det.detect(Image.new("RGB", (8, 8)))
        assert regions == [] and err.startswith("parse_error")
    finally:
        det.close()


def test_device_selects_paddle_wheel():
    """device='gpu' -> the worker installs paddlepaddle-gpu and gets device as an argument;
    cpu (the default) -> paddlepaddle."""
    cpu = DocLayoutDetector(device="cpu")
    gpu = DocLayoutDetector(device="gpu")
    assert any(a.startswith("paddlepaddle==") for a in cpu.worker_cmd)
    assert cpu.worker_cmd[-1] == "cpu"
    assert any(a.startswith("paddlepaddle-gpu==") for a in gpu.worker_cmd)
    assert not any(a.startswith("paddlepaddle==") for a in gpu.worker_cmd)  # not both at once
    assert "paddlepaddle.org.cn" in " ".join(gpu.worker_cmd)  # GPU build from the paddle index, not PyPI
    assert gpu.worker_cmd[-1] == "gpu"


def test_worker_death_is_transport_error(tmp_path):
    det = _det(tmp_path, "sys.exit(0)\n")
    try:
        with pytest.raises(TransportError, match="doclayout worker"):
            det.detect(Image.new("RGB", (8, 8)))
        assert det._proc is None
    finally:
        det.close()
