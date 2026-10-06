"""Evaluation of figure (Picture block) detection against gold boxes."""
from __future__ import annotations

import json
from pathlib import Path

Box = tuple[int, int, int, int]


def _gold_data(golden_dir: Path, page_id: str) -> tuple[Path, dict] | None:
    p = Path(golden_dir) / f"{page_id}.figures.json"
    if not p.exists():
        return None
    return p, json.loads(p.read_text(encoding="utf-8"))


def load_gold_figures(golden_dir: Path, page_id: str) -> list[Box] | None:
    """Gold figure boxes from <id>.figures.json; None if there is no file."""
    found = _gold_data(golden_dir, page_id)
    if found is None:
        return None
    return [tuple(round(v) for v in b) for b in found[1].get("figures", [])]


def load_gold_split(golden_dir: Path, page_id: str) -> tuple[list[Box], list[Box]] | None:
    """(standalone figures, sketches in table cells) by the gold "in_table" mark: a list of indices into "figures".

    Without the mark all figures are standalone. None if there is no file."""
    found = _gold_data(golden_dir, page_id)
    if found is None:
        return None
    path, data = found
    boxes = [tuple(round(v) for v in b) for b in data.get("figures", [])]
    idx = data.get("in_table", [])
    if not isinstance(idx, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(boxes) for i in idx):
        raise ValueError(f"{path}: in_table must be a list of indices into figures (0..{len(boxes) - 1})")
    inside = set(idx)
    return [b for i, b in enumerate(boxes) if i not in inside], [boxes[i] for i in sorted(inside)]


def _valid(b) -> bool:
    return (isinstance(b, (list, tuple)) and len(b) == 4
            and all(isinstance(v, (int, float)) for v in b) and b[2] > b[0] and b[3] > b[1])


def pred_figures(blocks: list[dict] | None) -> list[Box] | None:
    """Picture block boxes of a run; None if there are no blocks (model without layout)."""
    if not blocks:
        return None
    return [tuple(round(v) for v in b["bbox"]) for b in blocks
            if b.get("category") == "Picture" and _valid(b.get("bbox"))]


def table_boxes(blocks: list[dict] | None) -> list[Box]:
    """Table block boxes of a run."""
    return [tuple(round(v) for v in b["bbox"]) for b in blocks or []
            if b.get("category") == "Table" and _valid(b.get("bbox"))]


def in_table(box: Box, tables: list[Box]) -> bool:
    """The box center lies inside some table box."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(t[0] <= cx <= t[2] and t[1] <= cy <= t[3] for t in tables)


def split_by_tables(boxes: list[Box], tables: list[Box]) -> tuple[list[Box], list[Box]]:
    """(outside tables, inside tables)."""
    outside = [b for b in boxes if not in_table(b, tables)]
    return outside, [b for b in boxes if in_table(b, tables)]


def iou(a: Box, b: Box) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_boxes(pred: list[Box], gold: list[Box], iou_thr: float = 0.5) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matching by descending IoU: [(pred index, gold index, IoU)]."""
    pairs = sorted(((iou(p, g), i, j) for i, p in enumerate(pred) for j, g in enumerate(gold)), reverse=True)
    used_p, used_g, out = set(), set(), []
    for v, i, j in pairs:
        if v < iou_thr:
            break
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        out.append((i, j, v))
    return out


def figure_scores(pred: list[Box] | None, gold: list[Box], iou_thr: float = 0.5) -> dict | None:
    """Precision/recall/F1 from greedy matching.

    Edge cases: gold and pred empty -> all 1.0; gold empty, pred not ->
    precision 0, recall 1.0 (nothing to miss, but all predictions are extra);
    pred None (model without layout) -> None.
    """
    if pred is None:
        return None
    ious = [v for _, _, v in match_boxes(pred, gold, iou_thr)]
    matched, n_pred, n_gold = len(ious), len(pred), len(gold)
    if n_pred == 0 and n_gold == 0:
        precision = recall = f1 = 1.0
    else:
        precision = matched / n_pred if n_pred else 0.0
        recall = matched / n_gold if n_gold else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "matched": matched,
            "n_pred": n_pred, "n_gold": n_gold,
            "mean_iou": sum(ious) / matched if matched else 0.0}


def split_figure_counts(pred: list[Box], gold_out: list[Box], gold_in: list[Box]) -> list[int]:
    """[matched_out, n_pred_out, n_gold_out, matched_in, n_gold_in].

    Sketches in cells are matched first (recall only for them), the rest against standalone
    figures (precision and recall)."""
    m_in = match_boxes(pred, gold_in)
    used = {i for i, _, _ in m_in}
    rest = [b for i, b in enumerate(pred) if i not in used]
    m_out = match_boxes(rest, gold_out)
    return [len(m_out), len(rest), len(gold_out), len(m_in), len(gold_in)]


def figure_cells(fig: list[int]) -> tuple[str, str]:
    """Report cells: "P/R of standalone figures", "recall of sketches (found/total)" or "—"."""
    m, n_pred, n_gold, m_in, n_in = fig
    p = m / n_pred if n_pred else (1.0 if not n_gold else 0.0)
    r = m / n_gold if n_gold else 1.0
    thumb = f"{m_in / n_in:.2f} ({m_in}/{n_in})" if n_in else "—"
    return f"{p:.2f}/{r:.2f}", thumb
