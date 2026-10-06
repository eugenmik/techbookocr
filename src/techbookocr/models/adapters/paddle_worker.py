"""PaddleOCR-VL worker: JSON lines {"image": path} on stdin -> {"blocks": [...]} / {"error": ...} on stdout.

Runs in a separate environment (uv run --no-project --with paddleocr[doc-parser] ...).
Arguments: <vllm base_url> <served model name>.
"""
import json
import os
import sys


def main() -> None:
    # the protocol goes on a duplicate of fd 1; everything else (including C extensions) writes to stderr
    out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    from paddleocr import PaddleOCRVL

    pipe = PaddleOCRVL(pipeline_version="v1.6", vl_rec_backend="vllm-server", vl_rec_server_url=sys.argv[1],
                       vl_rec_api_model_name=sys.argv[2], device="cpu")
    out.write(json.dumps({"ready": True}) + "\n")
    out.flush()
    for line in sys.stdin:
        try:
            req = json.loads(line)
            blocks = []
            for res in pipe.predict(req["image"]):
                data = res.json
                data = data.get("res", data)
                for b in data["parsing_res_list"]:
                    blocks.append({"label": b["block_label"], "bbox": b["block_bbox"], "content": b["block_content"]})
            msg = {"blocks": blocks}
        except Exception as e:  # noqa: BLE001 — a page error is sent back to the client
            msg = {"error": f"{type(e).__name__}: {e}"}
        out.write(json.dumps(msg, ensure_ascii=False) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
