"""Cascade on the gold set: gold pages as a mini-book through the real pipeline, per-page scoring,
threshold sweep without models (replay), report eval/cascade-report.md."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from statistics import mean

from PIL import Image

from techbookocr.config import Config, ConfigError
from techbookocr.eval.figures import figure_cells, load_gold_split, split_figure_counts
from techbookocr.eval.golden import golden_pairs
from techbookocr.eval.metrics import score_page
from techbookocr.eval.report import _COLS, _avg, _fmt, _run_figures
from techbookocr.pipeline.arbiter import _words, judge, kept_fixes, sanitize_fixes
from techbookocr.pipeline.consensus import decide
from techbookocr.pipeline.guard import guarded_b, sibling_index
from techbookocr.pipeline.runner import RunOptions, finish_book, run_pages
from techbookocr.pipeline.state import STAGES, BookState, PageEntry

_ANCHOR = re.compile(r"<!-- page: \S+ scan: (\S+) -->")


def golden_entries(golden_dir: Path) -> list[PageEntry]:
    entries = []
    for i, (gp, png, _) in enumerate(golden_pairs(golden_dir)):
        with Image.open(png) as im:
            w, h = im.size
        entries.append(PageEntry(name=gp.id, idx=i, scan=gp.scan, side=gp.side, file=str(Path(png).resolve()),
                                 width=w, height=h))
    return entries


def _copy_state(src_dir: Path, dst_dir: Path) -> None:
    (dst_dir / "work").mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = src_dir / "work" / f"state.sqlite{suffix}"
        if src.exists():
            shutil.copy(src, dst_dir / "work" / src.name)


def _variant_info(out_dir: Path) -> dict | None:
    """Recorded variant parameters, or None if there is no state directory."""
    db = Path(out_dir) / "work" / "state.sqlite"
    if not db.exists():
        return None
    with BookState(db) as st:
        try:
            info = json.loads(st.get_meta("variant", "{}") or "{}")
        except json.JSONDecodeError:
            info = {}
    return info if isinstance(info, dict) else {}


def _seed_variant(seed: Path, out_dir: Path) -> None:
    """Atomically: a copy of the seed is assembled in a temp directory alongside, the arbiter is reset, then rename."""
    tmp = out_dir.parent / f".{out_dir.name}.seed-tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        _copy_state(seed, tmp)
        if (seed / "images").exists():
            shutil.copytree(seed / "images", tmp / "images")
        with BookState(tmp / "work" / "state.sqlite") as st:
            st.reset_stage("arbiter")
        if out_dir.exists():
            shutil.rmtree(out_dir)  # a directory without state.sqlite is a leftover of an interrupted run
        os.replace(tmp, out_dir)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def run_golden(cfg: Config, golden_dir: Path, out_dir: Path, *, arbiter: str, mode: str = "cascade",
               sweep: bool = False, seed: Path | None = None, **deps) -> Path:
    """Run the gold set through the pipeline. sweep: all mismatching blocks go to the arbiter (tau_text = -1).
    seed is the variant whose layout, sketches and drafts are used; only the arbiter is recomputed.

    Variant parameters are written to meta "variant" BEFORE the run; a directory with a different arbiter/mode/sweep (and for a regular
    variant, different thresholds) is not reused: ConfigError."""
    out_dir = Path(out_dir)
    p = cfg.pipeline
    want = {"arbiter": arbiter, "mode": mode, "sweep": sweep, "tau_text": -1.0 if sweep else p.tau_text,
            "tau_halluc": p.tau_halluc, "halluc_abs_chars": p.halluc_abs_chars}
    have = _variant_info(out_dir)
    if have is None and seed is not None:
        _seed_variant(Path(seed), out_dir)
        have = {}  # the seed's metadata: not this variant's
    if have:
        keys = ["arbiter", "mode", "sweep"] + ([] if sweep else ["tau_text", "tau_halluc", "halluc_abs_chars"])
        diff = {k: (have.get(k), want[k]) for k in keys if k in have and have[k] != want[k]}
        if diff:
            raise ConfigError(f"{out_dir} holds another variant (stored vs requested): {diff}; use another "
                              "directory or delete it")
    pipeline = replace(p, arbiter_model=arbiter, tau_text=want["tau_text"])
    with BookState(out_dir / "work" / "state.sqlite") as st:
        st.set_meta("variant", json.dumps(want))
        st.set_meta("golden_complete", "0")
    run_pages(golden_entries(golden_dir), out_dir, replace(cfg, pipeline=pipeline), RunOptions(mode=mode, lang="ru"),
              book_name="golden", source=str(golden_dir), **deps)
    with BookState(out_dir / "work" / "state.sqlite") as st:
        st.set_meta("golden_complete", "1")
    return out_dir


def incomplete_reason(variant_dir: Path) -> str | None:
    """Why a variant cannot be scored: unprocessed items remain or there is no completion mark."""
    with BookState(Path(variant_dir) / "work" / "state.sqlite") as st:
        left = {s: st.pending(s) for s in STAGES if st.pending(s)}
        if left:
            return "stages not finished: " + ", ".join(f"{s} ({n})" for s, n in left.items())
        if st.get_meta("golden_complete") != "1":
            return "no run completion mark"
    return None


def split_pages(md: str) -> dict[str, str]:
    """book.md -> {page name: its Markdown}; an anchor inside a stitched paragraph splits it between pages."""
    parts = _ANCHOR.split(md)
    out: dict[str, str] = {}
    for name, text in zip(parts[1::2], parts[2::2]):
        out[name] = out.get(name, "") + text
    return out


_KEEP_NOTES = ("image", "poison", "gave up")  # run_arbiter/runner notes about failures outside judge
_PARSE_NOTES = ("fixes unparsable",)  # reply-parsing note (pnote in run_arbiter)


def replay(state: BookState, tau_text: float, tau_halluc: float, mode: str, halluc_abs_chars: int = 3,
           lang: str = "ru") -> None:
    """Recompute decisions and totals from recorded drafts and arbiter replies, without models.

    Mirror of consensus + run_arbiter: the same judge(), the fixes selection condition and the note `v.note or pnote`
    (pnote is the reply-parsing note, recorded in arbiter_note during the run)."""
    blocks = state.blocks()
    index = sibling_index(blocks)
    corpus: dict[str, int] = {}
    for blk in blocks:
        for dr in (blk.text_a, blk.text_b):
            if dr:
                for w in _words(dr):
                    corpus[w.lower()] = corpus.get(w.lower(), 0) + 1
    with state.transaction():
        for b in blocks:
            text_b = guarded_b(b, index)
            d = decide(b.kind, b.text_a, text_b, tau_text, mode)
            if d.decision != "arbiter":
                state.update_block(b.id, decision=d.decision, cer_ab=d.cer, final=d.final,
                                   final_source=d.final_source, arbiter_status="skipped", fixes=[])
                continue
            error = None if b.arbiter_text is not None else (b.arbiter_error or "not arbitrated")
            drafts = [x for x in (b.text_a, text_b) if x and x.strip()]
            arb_text, bad = b.arbiter_text, []
            if b.arbiter_fixes:
                arb_text, ok_fixes, bad = sanitize_fixes(b.arbiter_text or "", b.arbiter_fixes, corpus, drafts)
            else:
                ok_fixes = b.arbiter_fixes
            v = judge(b.kind, b.text_a, text_b, arb_text, error, tau_halluc, lang, halluc_abs_chars)
            kept = kept_fixes(ok_fixes, drafts, v)
            pnote = b.arbiter_note if b.arbiter_text is not None and b.arbiter_note in _PARSE_NOTES else None
            note = v.note or pnote
            if bad:
                extra = "fixes reverted: " + "; ".join(f"{f['was']} → {f['now']} ({f['rejected']})" for f in bad)
                note = f"{note}; {extra}" if note else extra
            if b.arbiter_text is None and b.arbiter_note in _KEEP_NOTES:
                note = b.arbiter_note
            state.update_block(b.id, decision="arbiter", cer_ab=d.cer, final=v.final, final_source=v.source,
                               arbiter_status=v.status, arbiter_note=note, arbiter_cer=v.cer, fixes=kept + bad)


def _cat_rows(cats: dict) -> dict:
    """{category: (CER, Numbers F1, TEDS, page count)}."""
    return {c: (_avg(s.cer for s in ss), _avg(s.num_f1 for s in ss), _avg(s.teds for s in ss), len(ss))
            for c, ss in cats.items()}


def score_variant(out_dir: Path, golden_dir: Path) -> dict:
    pages_md = split_pages((Path(out_dir) / "book.md").read_text(encoding="utf-8"))
    with BookState(Path(out_dir) / "work" / "state.sqlite") as st:
        pages, blocks = st.pages(), st.blocks()
    scores, cats, fig, has_split = [], {}, [0, 0, 0, 0, 0], False
    for gp, _, gold_md in golden_pairs(golden_dir):
        s = score_page(pages_md.get(gp.id, ""), gold_md.read_text(encoding="utf-8"))
        scores.append(s)
        for c in gp.categories:
            cats.setdefault(c, []).append(s)
        gold = load_gold_split(golden_dir, gp.id)
        if gold is not None:
            has_split = True
            pred = [b.bbox for b in blocks if b.page == gp.id and b.category == "Picture" and b.parent is None and b.bbox]
            pred += [tuple(sk["bbox"]) for b in blocks if b.page == gp.id for sk in b.sketches]
            fig = [x + y for x, y in zip(fig, split_figure_counts(pred, *gold))]
    draftable = [b for b in blocks if b.kind is not None and b.parent is None]
    arbitrated = [b for b in draftable if b.decision == "arbiter"]
    infer = (sum(p.layout_seconds or 0 for p in pages) + sum(b.b_seconds or 0 for b in blocks)
             + sum(b.arbiter_seconds or 0 for b in arbitrated))
    return {"avg": {attr: _avg(getattr(s, attr) for s in scores) for _, attr in _COLS},
            "cats": _cat_rows(cats),
            "fig": fig if has_split else None, "arbitration": len(arbitrated) / len(draftable) if draftable else 0.0,
            "rejected": sum(b.arbiter_status == "rejected" for b in blocks),
            "sec_per_page": infer / max(1, len(pages))}


def evaluate(variant_dir: Path, golden_dir: Path, tau_text: float, tau_halluc: float, speller=None,
             halluc_abs_chars: int = 3) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        _copy_state(Path(variant_dir), out)
        with BookState(out / "work" / "state.sqlite") as st:
            mode = json.loads(st.get_meta("variant", "{}")).get("mode", "cascade")
            lang = st.get_meta("lang", "ru")
            replay(st, tau_text, tau_halluc, mode, halluc_abs_chars, lang)
            finish_book(st, out, book_name="golden", source=str(golden_dir), lang=lang, mode=mode, models={},
                        speller=speller)
        return score_variant(out, golden_dir)


def single_rows(golden_dir: Path, runs_dir: Path) -> dict[str, dict]:
    pages = golden_pairs(golden_dir)
    has_split = any(load_gold_split(golden_dir, gp.id) is not None for gp, _, _ in pages)
    rows = {}
    for run in sorted(p for p in Path(runs_dir).iterdir() if p.is_dir()):
        scores, secs, cats = [], [], {}
        for gp, _, gold_md in pages:
            pred = run / f"{gp.id}.md"
            sc = score_page(pred.read_text(encoding="utf-8") if pred.exists() else "",
                            gold_md.read_text(encoding="utf-8"))
            scores.append(sc)
            for c in gp.categories:
                cats.setdefault(c, []).append(sc)
            try:
                secs.append(float(json.loads((run / f"{gp.id}.json").read_text(encoding="utf-8"))["seconds"]))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        rows[run.name] = {"avg": {attr: _avg(getattr(s, attr) for s in scores) for _, attr in _COLS},
                          "fig": _run_figures(run, pages, golden_dir) if has_split else None,
                          "cats": _cat_rows(cats), "sec_per_page": mean(secs) if secs else None}
    return rows


def _row(name: str, r: dict, thr: str = "—", arb: str = "—", rej: str = "—") -> str:
    fig = figure_cells(r["fig"]) if r.get("fig") else ("—", "—")
    sec = f"{r['sec_per_page']:.1f}" if r.get("sec_per_page") is not None else "—"
    return (f"| {name} | {thr} | " + " | ".join(_fmt(r["avg"][a]) for _, a in _COLS)
            + f" | {fig[0]} | {fig[1]} | {sec} | {arb} | {rej} |")


def _best_single(singles: dict, cat: str) -> tuple[str, tuple] | None:
    cands = [(n, r["cats"][cat]) for n, r in singles.items() if cat in r.get("cats", {})]
    if not cands:
        return None
    return max(cands, key=lambda c: (c[1][1] if c[1][1] is not None else -1,
                                     -(c[1][0] if c[1][0] is not None else 9)))


def build_cascade_report(singles: dict, variants: dict, sweeps: dict, tau: tuple[float, float, int],
                         incomplete: dict[str, str] | None = None) -> str:
    out = ["# Cascade on the gold set", "",
           f"Variants with --sweep are scored at tau_text = {tau[0]}, tau_halluc = {tau[1]}, halluc_abs_chars = {tau[2]}; "
           "regular variants at their own thresholds (the \"Thresholds\" column). Time is pure inference per page "
           "(layout, B drafts, arbiter), without model loading; for single models, the run time from Plan 1.",
           "", "## Cascade and single models", "",
           "| Variant | Thresholds | " + " | ".join(c for c, _ in _COLS)
           + " | Figures outside tables P/R | Sketches in tables R | s/page | Arbitration | Rejected |",
           "|---|---|" + "---|" * (len(_COLS) + 5)]
    out += [_row(name, r, r.get("thresholds", "—"), f"{100 * r['arbitration']:.1f}%", str(r["rejected"]))
            for name, r in variants.items()]
    out += [_row(name, r) for name, r in singles.items()]
    for name, rows in sweeps.items():
        out += ["", f"## Threshold sweep: {name}", "",
                "| tau_text | tau_halluc | abs_chars | CER↓ | Numbers F1↑ | TEDS↑ | Formulas CER↓ | Arbitration | Rejected | s/page |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            a = r["avg"]
            out.append(f"| {r['tau_text']} | {r['tau_halluc']} | {r['halluc_abs_chars']} | {_fmt(a['cer'])} | "
                       f"{_fmt(a['num_f1'])} | {_fmt(a['teds'])} | {_fmt(a['formula_cer'])} | "
                       f"{100 * r['arbitration']:.1f}% | {r['rejected']} | {r['sec_per_page']:.1f} |")
    out += ["", "## By category (cascade)", "",
            "| Category | Variant | Pages | CER↓ | Numbers F1↑ | TEDS↑ |", "|---|---|---|---|---|---|"]
    for c in sorted({c for r in variants.values() for c in r["cats"]}):
        for name, r in variants.items():
            if c in r["cats"]:
                cer_, f1, t, n = r["cats"][c]
                out.append(f"| {c} | {name} | {n} | {_fmt(cer_)} | {_fmt(f1)} | {_fmt(t)} |")
        best = _best_single(singles, c)
        if best:
            cer_, f1, t, n = best[1]
            out.append(f"| {c} | best single: {best[0]} | {n} | {_fmt(cer_)} | {_fmt(f1)} | {_fmt(t)} |")
    if incomplete:
        out += ["", "## Incomplete variants", "", "Not included in the tables: results are incomplete."]
        out += [f"- {name}: {why}" for name, why in incomplete.items()]
    return "\n".join(out) + "\n"


def cascade_report(golden_dir: Path, runs_dir: Path, cascade_dir: Path, tau_text: float, tau_halluc: float,
                   grid_text: list[float], grid_halluc: list[float], grid_abs: list[int] | None = None,
                   speller=None, halluc_abs_chars: int = 3) -> str:
    variants, sweeps, incomplete = {}, {}, {}
    for d in sorted(p for p in (Path(cascade_dir).iterdir() if Path(cascade_dir).exists() else [])
                    if (p / "work" / "state.sqlite").exists()):
        why = incomplete_reason(d)
        if why:
            incomplete[d.name] = why
            continue
        info = _variant_info(d) or {}
        if info.get("sweep"):
            thr = f"{tau_text} / {tau_halluc} / {halluc_abs_chars}"
            variants[d.name] = {**evaluate(d, golden_dir, tau_text, tau_halluc, speller, halluc_abs_chars),
                                "thresholds": thr}
            sweeps[d.name] = [{**evaluate(d, golden_dir, tt, th, speller, ac), "tau_text": tt, "tau_halluc": th,
                               "halluc_abs_chars": ac}
                              for tt in grid_text for th in grid_halluc for ac in (grid_abs or [halluc_abs_chars])]
        else:  # a regular variant is scored at the run's thresholds: arbiter replies exist only for them
            tt, th, ac = (info.get("tau_text", tau_text), info.get("tau_halluc", tau_halluc),
                          info.get("halluc_abs_chars", halluc_abs_chars))
            variants[d.name] = {**evaluate(d, golden_dir, tt, th, speller, ac), "thresholds": f"{tt} / {th} / {ac}"}
    singles = single_rows(golden_dir, runs_dir) if Path(runs_dir).exists() else {}
    return build_cascade_report(singles, variants, sweeps, (tau_text, tau_halluc, halluc_abs_chars), incomplete)
