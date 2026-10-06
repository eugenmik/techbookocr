"""Run candidate models over the gold set with output caching."""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from techbookocr.config import Config
from techbookocr.eval.golden import GoldenPage, golden_pairs
from techbookocr.models.errors import TransportError
from techbookocr.models.server import ServerError, gpu_memory_used_mib, server_for
from techbookocr.models.types import PageOCR


MAX_CONSECUTIVE_TRANSPORT_ERRORS = 3
_TRANSPORT = (TransportError, ConnectionError, TimeoutError, ServerError)


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def run_model(ocr: PageOCR, pages: list[tuple[GoldenPage, Path, Path]], out_dir: Path) -> list[dict]:
    """Run the pages. Transport failures are not cached (the page is finished on a rerun);
    after MAX_CONSECUTIVE_TRANSPORT_ERRORS in a row the model is aborted with a TransportError exception."""
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    transport_streak = 0
    for gp, png, _ in pages:
        md_path = out_dir / f"{gp.id}.md"
        meta_path = out_dir / f"{gp.id}.json"

        # Check if page is already done: both files exist and JSON parses
        if md_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                records.append({"id": gp.id, "seconds": meta["seconds"], "error": meta["error"]})
                continue
            except (json.JSONDecodeError, ValueError, KeyError, TypeError):
                pass  # Recompute if JSON is corrupted

        t0 = time.monotonic()
        try:
            res = ocr.ocr_page(Image.open(png).convert("RGB"))
            md, meta = res.markdown, {"raw": res.raw, "seconds": res.seconds or time.monotonic() - t0,
                                      "error": res.error, "blocks": [asdict(b) for b in res.blocks]}
            transport_streak = 0
        except _TRANSPORT as e:
            transport_streak += 1
            records.append({"id": gp.id, "seconds": time.monotonic() - t0, "error": f"transport: {e}"})
            if transport_streak >= MAX_CONSECUTIVE_TRANSPORT_ERRORS:
                raise TransportError(f"{transport_streak} consecutive transport errors, last on {gp.id}: {e}") from e
            continue
        except Exception as e:  # a page failure does not stop the run
            transport_streak = 0
            md, meta = "", {"raw": traceback.format_exc(), "seconds": time.monotonic() - t0,
                            "error": f"{type(e).__name__}: {e}", "blocks": []}

        _write_atomic(md_path, md)
        _write_atomic(meta_path, json.dumps(meta, ensure_ascii=False, indent=1))

        records.append({"id": gp.id, "seconds": meta["seconds"], "error": meta["error"]})
    return records


class _VramSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.peak, self._stop_event = 0, threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                self.peak = max(self.peak, gpu_memory_used_mib())
            except Exception:
                pass
            self._stop_event.wait(1.0)

    def stop(self) -> int:
        self._stop_event.set()
        self.join(timeout=5)
        return self.peak


def run_candidates(cfg: Config, keys: list[str], golden_dir: Path, runs_dir: Path, server_factory=None) -> list[str]:
    from techbookocr.models.registry import make_adapter

    if server_factory is None:
        server_factory = server_for

    pages = golden_pairs(golden_dir)
    failed = []

    for key in keys:
        spec = cfg.models[key]
        out = runs_dir / key
        if all((out / f"{gp.id}.json").exists() and (out / f"{gp.id}.md").exists() for gp, _, _ in pages):
            continue

        sampler = _VramSampler()
        try:
            with server_factory(spec, cfg.server) as server:
                sampler.start()
                try:
                    ocr = make_adapter(spec, server.base_url)
                    try:
                        run_model(ocr, pages, out)
                    finally:
                        ocr.close()
                finally:
                    peak = sampler.stop()

            # Update _meta.json with peak VRAM (keep max if file exists)
            meta_path = out / "_meta.json"
            existing_peak = 0
            if meta_path.exists():
                try:
                    existing = json.loads(meta_path.read_text(encoding="utf-8"))
                    existing_peak = existing.get("peak_vram_mib", 0)
                except (json.JSONDecodeError, ValueError):
                    pass
            peak = max(peak, existing_peak)
            _write_atomic(meta_path, json.dumps({"peak_vram_mib": peak}))
            # Clear any previous failure marker on successful run
            (out / "_failed.txt").unlink(missing_ok=True)
        except Exception as e:
            failed.append(key)
            out.mkdir(parents=True, exist_ok=True)
            (out / "_failed.txt").write_text(f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}", encoding="utf-8")

    return failed
