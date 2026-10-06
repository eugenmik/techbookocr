"""Summary report over candidate runs."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from techbookocr.eval.figures import figure_cells, load_gold_split, pred_figures, split_figure_counts
from techbookocr.eval.golden import golden_pairs
from techbookocr.eval.metrics import score_page

_COLS = [("CER↓", "cer"), ("WER↓", "wer"), ("Numbers F1↑", "num_f1"), ("TEDS↑", "teds"),
         ("TEDS-struct↑", "teds_struct"), ("Formulas CER↓", "formula_cer"), ("Order↑", "order")]


def _avg(values) -> float | None:
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else None


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.3f}"


def _run_figures(run: Path, pages, golden_dir: Path) -> list[int] | None:
    """Pooled [matched_out, n_pred_out, n_gold_out, matched_in, n_gold_in] of a run, or None (model without layout).

    The gold set is split by the "in_table" mark in <id>.figures.json: one split for all models. Predicted
    Pictures are first matched against sketches in cells, the rest against standalone figures. A model counts as
    a layout model if any page has blocks; pages of such a model with no output or with empty
    blocks count as zero predictions.
    """
    per_page, any_layout = [], False
    for gp, _, _ in pages:
        blocks = None
        try:
            meta = json.loads((run / f"{gp.id}.json").read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                blocks = meta.get("blocks")
        except (OSError, ValueError):
            pass
        any_layout = any_layout or bool(blocks)
        gold = load_gold_split(golden_dir, gp.id)
        if gold is not None:
            per_page.append((gold, blocks))
    if not any_layout:
        return None
    fig = [0, 0, 0, 0, 0]
    for (gold_out, gold_in), blocks in per_page:
        counts = split_figure_counts(pred_figures(blocks) or [], gold_out, gold_in)
        fig = [a + b for a, b in zip(fig, counts)]
    return fig


def build_report(golden_dir: Path, runs_dir: Path) -> str:
    pages = golden_pairs(golden_dir)
    rows, by_cat, errors = [], defaultdict(dict), []
    for run in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        scores, secs, errs, missing = [], [], 0, 0
        cats: dict[str, list] = defaultdict(list)
        for gp, _, gold_md in pages:
            pred = run / f"{gp.id}.md"
            meta_p = run / f"{gp.id}.json"

            # Handle missing/unreadable files
            if not pred.exists() or not meta_p.exists():
                missing += 1
                s = score_page("", gold_md.read_text(encoding="utf-8"))
                scores.append(s)
                # Do NOT add to secs; missing pages don't count in time average
                for c in gp.categories:
                    cats[c].append(s)
                continue

            try:
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                missing += 1
                s = score_page("", gold_md.read_text(encoding="utf-8"))
                scores.append(s)
                # Do NOT add to secs; missing pages don't count in time average
                for c in gp.categories:
                    cats[c].append(s)
                continue

            s = score_page(pred.read_text(encoding="utf-8"), gold_md.read_text(encoding="utf-8"))
            scores.append(s)
            meta = meta if isinstance(meta, dict) else {}
            if isinstance(meta.get("seconds"), (int, float)):
                secs.append(meta["seconds"])
            errs += "seconds" not in meta or "error" not in meta or meta["error"] is not None  # no fields -> error
            for c in gp.categories:
                cats[c].append(s)

        if not scores:
            continue
        fig = _run_figures(run, pages, golden_dir)
        fig_seen = fig is not None
        vram = None
        meta_path = run / "_meta.json"
        if meta_path.exists():
            try:
                vram = json.loads(meta_path.read_text(encoding="utf-8")).get("peak_vram_mib")
            except (json.JSONDecodeError, ValueError):
                pass

        avg = {attr: _avg(getattr(s, attr) for s in scores) for _, attr in _COLS}
        # Only average times for pages that have seconds (not missing)
        sec_avg = mean(secs) if secs else 0
        fig_cell, thumb_cell = figure_cells(fig) if fig_seen else ("—", "—")
        rows.append((run.name, avg, sec_avg, vram, len(scores), fig_cell, thumb_cell))
        for c, ss in cats.items():
            by_cat[c][run.name] = (_avg(s.cer for s in ss), _avg(s.num_f1 for s in ss), _avg(s.teds for s in ss))

        # Report errors and missing as disjoint counts
        error_parts = []
        if errs:
            error_parts.append(f"{errs} errors")
        if missing:
            error_parts.append(f"{missing} pages missing")
        if error_parts:
            errors.append(f"- {run.name}: {', '.join(error_parts)}")

    rows.sort(key=lambda r: (-(r[1]["num_f1"] or 0), 1 if r[1]["cer"] is None else r[1]["cer"]))
    out = ["# Model comparison on the gold set", "",
           "| Model | " + " | ".join(c for c, _ in _COLS) + " | Figures outside tables P/R | Sketches in tables R | s/page | VRAM MiB | pages |",
           "|---|" + "---|" * (len(_COLS) + 5)]
    for name, avg, sec, vram, n, fig_cell, thumb_cell in rows:
        out.append(f"| {name} | " + " | ".join(_fmt(avg[a]) for _, a in _COLS) + f" | {fig_cell} | {thumb_cell} | {sec:.1f} | {vram or '—'} | {n} |")
    out += ["", "## By category", "", "| Category | Model | CER↓ | Numbers F1↑ | TEDS↑ |", "|---|---|---|---|---|"]
    for c in sorted(by_cat):
        for name, (cer, f1, t) in sorted(by_cat[c].items(), key=lambda kv: -(kv[1][1] or 0)):
            out.append(f"| {c} | {name} | {_fmt(cer)} | {_fmt(f1)} | {_fmt(t)} |")
    out += ["", "## Errors", ""] + (errors or ["- none"])
    return "\n".join(out) + "\n"
