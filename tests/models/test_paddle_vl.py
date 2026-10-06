import sys
import time

import pytest
from PIL import Image

from techbookocr.config import ModelSpec
from techbookocr.models.errors import TransportError
from techbookocr.models.adapters.paddle_vl import PaddleVLAdapter, blocks_from_paddle

SPEC = ModelSpec(key="p", adapter="paddle_vl", image="i", model="PaddlePaddle/PaddleOCR-VL-1.6")


def test_label_mapping():
    items = [
        {"label": "paragraph_title", "bbox": [1, 2, 3, 4], "content": "Чугун"},
        {"label": "table", "bbox": [0, 0, 1, 1], "content": "<table><tr><td>1</td></tr></table>"},
        {"label": "display_formula", "bbox": [0, 0, 1, 1], "content": "$$x$$"},
        {"label": "header", "bbox": [0, 0, 1, 1], "content": "61"},
        {"label": "image", "bbox": [0, 0, 1, 1], "content": ""},
        {"label": "something_new", "bbox": [0, 0, 1, 1], "content": "т"},
    ]
    blocks = blocks_from_paddle(items, (1000, 1000))
    assert [b.category for b in blocks] == ["Section-header", "Table", "Formula", "Page-header", "Picture", "Text"]
    assert blocks[0].bbox == (1, 2, 3, 4)


FAKE_WORKER = """
import json, sys
print("noise from paddle import")
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    print("log line")
    print(json.dumps({"blocks": [{"label": "text", "bbox": [0, 0, 5, 5], "content": "Привет"}]}, ensure_ascii=False), flush=True)
"""


def test_adapter_talks_to_worker(tmp_path):
    script = tmp_path / "w.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")
    a = PaddleVLAdapter(SPEC, None, "http://x/v1", worker_cmd=[sys.executable, str(script)])
    try:
        res = a.ocr_page(Image.new("RGB", (10, 10), "white"))
        res2 = a.ocr_page(Image.new("RGB", (10, 10), "white"))
    finally:
        a.close()
    assert res.markdown == "Привет\n" and res.error is None and res2.markdown == "Привет\n"


def test_worker_error_reported(tmp_path):
    script = tmp_path / "w.py"
    script.write_text('import json,sys\nprint(json.dumps({"ready": True}),flush=True)\n'
                      'for l in sys.stdin:\n    print(json.dumps({"error": "boom"}),flush=True)\n', encoding="utf-8")
    a = PaddleVLAdapter(SPEC, None, "http://x/v1", worker_cmd=[sys.executable, str(script)])
    try:
        res = a.ocr_page(Image.new("RGB", (10, 10)))
    finally:
        a.close()
    assert res.error == "boom" and res.markdown == ""


def test_blocks_from_paddle_handles_odd_items():
    """Test that blocks_from_paddle gracefully handles odd items."""
    items = [
        {"label": "text", "bbox": [0, 0, 5, 5], "content": "ok"},
        "not a dict",  # non-dict item
        {"label": "text", "bbox": [0, 0], "content": "short bbox"},  # short bbox
        {"label": "text", "bbox": "not_a_list", "content": "non-list bbox"},  # non-list bbox
        {"label": "text", "bbox": [0, 0, "three", 5], "content": "non-numeric bbox"},  # non-numeric bbox
        {"label": "text", "content": "missing bbox"},  # missing bbox
        {"label": "text"},  # missing content
    ]
    blocks = blocks_from_paddle(items, (1000, 1000))
    # Non-dict item is skipped
    # All other items become blocks (odd bbox issues degrade to bbox=None)
    assert len(blocks) == 6
    assert blocks[0].text == "ok" and blocks[0].bbox == (0, 0, 5, 5)
    assert blocks[1].text == "short bbox" and blocks[1].bbox is None
    assert blocks[2].text == "non-list bbox" and blocks[2].bbox is None
    assert blocks[3].text == "non-numeric bbox" and blocks[3].bbox is None
    assert blocks[4].text == "missing bbox" and blocks[4].bbox is None
    assert blocks[5].text == "" and blocks[5].bbox is None  # missing content is empty string


def test_adapter_handles_worker_exit(tmp_path):
    """Test that adapter handles worker exit gracefully (doesn't hang)."""
    # Worker that exits after sending ready
    script = tmp_path / "w.py"
    script.write_text('import json,sys,time\nprint(json.dumps({"ready": True}),flush=True)\n'
                      'time.sleep(0.3)\nsys.exit(0)\n', encoding="utf-8")
    a = PaddleVLAdapter(SPEC, None, "http://x/v1", worker_cmd=[sys.executable, str(script)])
    try:
        with pytest.raises(TransportError, match="exited"):
            a.ocr_page(Image.new("RGB", (10, 10)))
    finally:
        a.close()


def test_adapter_restarts_worker_after_exit(tmp_path):
    """Test that adapter restarts worker after it exits."""
    # Use a counter file to track worker starts
    counter_file = tmp_path / "counter"
    script = tmp_path / "w.py"
    worker_code = f"""import json,sys
counter_file = {repr(str(counter_file))}
try:
    with open(counter_file, "r") as f:
        count = int(f.read().strip() or "0")
except:
    count = 0
with open(counter_file, "w") as f:
    f.write(str(count + 1))
print(json.dumps({{"ready": True}}), flush=True)
for l in sys.stdin:
    req = json.loads(l)
    if count == 0:
        sys.exit(1)
    print(json.dumps({{"blocks": [{{"label": "text", "bbox": [0, 0, 5, 5], "content": "ok"}}]}}, ensure_ascii=False), flush=True)
"""
    script.write_text(worker_code, encoding="utf-8")
    a = PaddleVLAdapter(SPEC, None, "http://x/v1", worker_cmd=[sys.executable, str(script)])
    try:
        # First call: worker exits (count==0)
        with pytest.raises(TransportError):
            a.ocr_page(Image.new("RGB", (10, 10)))

        # Second call: worker should restart with count==1
        res2 = a.ocr_page(Image.new("RGB", (10, 10)))
        assert res2.error is None
        assert res2.markdown == "ok\n"
    finally:
        a.close()


def _adapter(tmp_path, code, **kw):
    script = tmp_path / "w.py"
    script.write_text(code, encoding="utf-8")
    return PaddleVLAdapter(SPEC, None, "http://x/v1", worker_cmd=[sys.executable, str(script)], **kw)


def test_worker_exit_is_deterministic_in_both_orders(tmp_path):
    # exits immediately after ready, with no sleep: BrokenPipe or EOF, either way a clean error
    a = _adapter(tmp_path, 'import json,sys\nprint(json.dumps({"ready": True}),flush=True)\n')
    try:
        for _ in range(3):
            with pytest.raises(TransportError, match="exited"):
                a.ocr_page(Image.new("RGB", (10, 10)))
            assert a._proc is None
    finally:
        a.close()


def test_hung_worker_times_out_and_is_killed(tmp_path):
    a = _adapter(tmp_path, 'import json,time\nprint(json.dumps({"ready": True}),flush=True)\ntime.sleep(3600)\n',
                 page_timeout=1)
    proc = None
    try:
        with pytest.raises(TransportError):
            a.ocr_page(Image.new("RGB", (4, 4)))
    finally:
        pass
    a2 = _adapter(tmp_path, 'import json,sys,time\nprint(json.dumps({"ready": True}),flush=True)\n'
                  'sys.stdin.readline()\ntime.sleep(3600)\n', page_timeout=1)
    try:
        a2._ensure_worker()
        proc = a2._proc
        t0 = time.monotonic()
        with pytest.raises(TransportError, match="paddle worker timeout"):
            a2.ocr_page(Image.new("RGB", (4, 4)))
        assert time.monotonic() - t0 < 10
        assert a2._proc is None and proc.poll() is not None
    finally:
        a2.close()
        a.close()


def test_malformed_replies(tmp_path):
    a = _adapter(tmp_path, 'import json,sys\nprint(json.dumps({"ready": True}),flush=True)\n'
                 'for l in sys.stdin:\n    print(json.dumps({"weird": 1}),flush=True)\n')
    try:
        res = a.ocr_page(Image.new("RGB", (4, 4)))
        assert res.error and res.markdown == ""
    finally:
        a.close()


def test_unready_first_line_kills_worker(tmp_path):
    a = _adapter(tmp_path, 'import json,time\nprint(json.dumps({"hello": 1}),flush=True)\ntime.sleep(3600)\n')
    try:
        with pytest.raises(TransportError):
            a.ocr_page(Image.new("RGB", (4, 4)))
        assert a._proc is None
    finally:
        a.close()


def test_blocks_from_paddle_never_raises():
    items = [{"label": ["x"], "bbox": (1, 2, 3, 4), "content": 5},
             {"label": "text", "bbox": [0, 0, float("inf"), 1], "content": "a"}, None, 7]
    blocks = blocks_from_paddle(items, (1000, 1000))
    assert [b.text for b in blocks] == ["5", "a"] and blocks[0].bbox == (1, 2, 3, 4) and blocks[1].bbox is None
    assert [b.order for b in blocks] == [0, 1]


def test_stderr_goes_to_log_file(tmp_path):
    log = tmp_path / "logs" / "w.log"
    a = _adapter(tmp_path, 'import json,sys\nsys.stderr.write("hello-stderr\\n")\n'
                 'print(json.dumps({"ready": True}),flush=True)\n'
                 'for l in sys.stdin:\n    print(json.dumps({"blocks": []}),flush=True)\n', stderr_path=log)
    try:
        a.ocr_page(Image.new("RGB", (4, 4)))
    finally:
        a.close()
    assert "hello-stderr" in log.read_text()


def test_paddle_bboxes_clamped():
    blocks = blocks_from_paddle([{"label": "text", "bbox": [-5, 3, 5000, 2000], "content": "a"},
                                 {"label": "text", "bbox": [9, 9, 3, 3], "content": "b"}], (100, 200))
    assert blocks[0].bbox == (0, 3, 100, 200) and blocks[1].bbox is None
