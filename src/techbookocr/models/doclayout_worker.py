"""PP-DocLayoutV3 worker: JSON lines {"image": path} on stdin -> {"boxes": [...]} / {"error": ...} on stdout.

Runs in a separate environment (uv run --no-project --with paddleocr[doc-parser] ...).
Arguments: detector confidence threshold (default 0.2; final filtering happens in
techbookocr.pipeline.sketches), device (cpu|gpu, default cpu; gpu requires paddlepaddle-gpu)."""
import json
import os
import sys


def main() -> None:
    # the protocol goes on a duplicate of fd 1; everything else (including C extensions) writes to stderr
    out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    from paddleocr import LayoutDetection

    threshold = float(sys.argv[1]) if len(sys.argv) > 1 else 0.2
    device = sys.argv[2] if len(sys.argv) > 2 else "cpu"
    model = LayoutDetection(model_name="PP-DocLayoutV3", device=device, threshold=threshold, layout_nms=True)
    out.write(json.dumps({"ready": True}) + "\n")
    out.flush()
    for line in sys.stdin:
        try:
            req = json.loads(line)
            boxes = []
            for res in model.predict(req["image"], batch_size=1):
                data = res.json
                data = data.get("res", data)
                for b in data["boxes"]:
                    boxes.append({"label": b["label"], "score": float(b["score"]),
                                  "bbox": [float(v) for v in b["coordinate"]]})
            msg = {"boxes": boxes}
        except Exception as e:  # noqa: BLE001 — a request error is sent back to the client
            msg = {"error": f"{type(e).__name__}: {e}"}
        out.write(json.dumps(msg, ensure_ascii=False) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
