"""quality.md and the book quality summary (which also goes into meta.json)."""
from __future__ import annotations


def quality_stats(pages, blocks, spell) -> dict:
    draftable = [b for b in blocks if b.kind is not None and b.parent is None]
    arbitrated = [b for b in draftable if b.decision == "arbiter"]
    done_with_notes = [b for b in blocks if b.arbiter_status == "done" and b.arbiter_note]
    unverified = sum(1 for b in done_with_notes if b.arbiter_note.startswith("unverified:"))
    kept = sum(1 for b in done_with_notes if b.arbiter_note.startswith("kept:"))
    fixes_unparsable = sum(1 for b in done_with_notes if "fixes unparsable" in b.arbiter_note)
    layer_pages = {b.page for b in blocks if b.origin == "layer"}
    return {
        "pages": len(pages),
        "layout_failed": sum(p.layout_status == "failed" for p in pages),
        "layer_pages": len(layer_pages),
        "vision_pending": sum(p.layout_status == "pending" for p in pages),
        "tables_pending": sum(b.origin == "layer" and b.category == "Table"
                              and b.arbiter_status == "pending" for b in blocks),
        "blocks": len(blocks),
        "draftable": len(draftable),
        "arbitrated": len(arbitrated),
        "arbitration_share": round(len(arbitrated) / len(draftable), 4) if draftable else 0.0,
        "arbiter_rejected": sum(b.arbiter_status == "rejected" for b in blocks),
        "arbiter_failed": sum(b.arbiter_status == "failed" for b in blocks),
        "drafts_failed": sum(b.drafts_status == "failed" for b in blocks),
        "sketches_failed": sum(b.sketches_status == "failed" for b in blocks),
        "sketches": sum(len(b.sketches) for b in blocks),
        "misprint_fixes": sum(1 for b in blocks for f in b.fixes if not f.get("rejected")),
        "misprint_reverted": sum(1 for b in blocks for f in b.fixes if f.get("rejected")),
        "spell_checked": spell.checked if spell else None,
        "spell_unknown": spell.unknown if spell else None,
        "unverified": unverified,
        "kept": kept,
        "fixes_unparsable": fixes_unparsable,
    }


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _ref(by_name: dict, name: str) -> str:
    p = by_name.get(name)
    return f"{name} (p. {p.printed})" if p is not None and p.printed else name


def _block_failure(b) -> str:
    parts = []
    if b.drafts_status == "failed":
        parts.append(f"draft B: {b.b_error}")
    if b.sketches_status == "failed":
        parts.append(f"sketches: {b.sketches_error}")
    return "; ".join(parts)


def render_quality(book_name: str, pages, blocks, stats: dict, spell, sketch_notes: list[str],
                   timings: dict[str, float], spans: dict | None = None, suspects: list | None = None) -> str:
    by_name = {p.name: p for p in pages}
    out = [f"# Recognition quality: {book_name}", "", "| Metric | Value |", "|---|---|",
           f"| Pages | {stats['pages']} (layout failed: {stats['layout_failed']}) |",
           f"| Blocks with draft B | {stats['draftable']} |",
           f"| Arbitrated share | {_pct(stats['arbitration_share'])} ({stats['arbitrated']} of {stats['draftable']}) |",
           f"| Arbiter answers rejected | {stats['arbiter_rejected']} |",
           f"| Arbiter failures | {stats['arbiter_failed']} |",
           f"| Failed drafts B | {stats['drafts_failed']} |",
           f"| Sketches in tables | {stats['sketches']} (detector failures: {stats['sketches_failed']}) |",
           f"| Misprint fixes | {stats['misprint_fixes']}" +
           (f" (reverted by guards: {stats['misprint_reverted']})" if stats.get('misprint_reverted') else "") + " |",
           f"| Out-of-dictionary words | {_pct(spell.share)} ({spell.unknown} of {spell.checked}) |" if spell
           else "| Out-of-dictionary words | dictionaries unavailable |"]
    if timings:
        n = max(1, stats["pages"])
        out += ["", "## Time per stage", "", "| Stage | Seconds | s/page |", "|---|---|---|"]
        out += [f"| {stage} | {s:.0f} | {s / n:.1f} |" for stage, s in timings.items()]
    if stats.get("layer_pages"):
        out += ["", "## Text-layer extraction", "",
                f"- Layer pages extracted: {stats['layer_pages']}",
                f"- Vision pages awaiting OCR (`--models`): {stats['vision_pending']}",
                f"- Tables awaiting arbiter (`--models`): {stats['tables_pending']}", "",
                "Pages awaiting OCR:"]
        pend = [p for p in pages if p.layout_status == "pending"]
        out += [f"- {_ref(by_name, p.name)}" for p in pend] or ["- none"]
        out += ["", "Tables awaiting arbiter:"]
        tabs = [b for b in blocks if b.origin == "layer" and b.category == "Table"
                and b.arbiter_status == "pending"]
        out += [f"- {_ref(by_name, b.page)}, block {b.ord}" for b in tabs] or ["- none"]
    failed_pages = [p for p in pages if p.layout_status == "failed"]
    out += ["", "## Layout failures", ""]
    out += [f"- {_ref(by_name, p.name)}: {p.layout_error or '—'}" for p in failed_pages] or ["- none"]
    bad_arbiter = [b for b in blocks if b.arbiter_status in ("rejected", "failed")]
    out += ["", "## Rejected and failed arbiter answers", ""]
    parts_arbiter = []
    for b in bad_arbiter:
        note = b.arbiter_note or ""
        error = b.arbiter_error or ""
        reason = " — ".join(filter(None, [note, error]))
        parts_arbiter.append(f"- {_ref(by_name, b.page)}, block {b.ord} ({b.kind}): {b.arbiter_status}, {reason} → {b.final_source}")
    out += parts_arbiter or ["- none"]
    to_review = [b for b in blocks if b.arbiter_status == "done" and b.arbiter_note and
                 (b.arbiter_note.startswith("unverified:") or b.arbiter_note.startswith("kept:") or
                  "fixes unparsable" in b.arbiter_note)]
    review = [f"- {_ref(by_name, b.page)}, block {b.ord} ({b.kind}): {b.arbiter_note}" for b in to_review]
    review += [f"- {_ref(by_name, page)}, block {ord_}: {desc}" for page, ord_, desc in (suspects or [])]
    out += ["", "## Needs manual review", ""] + (review or ["- none"])
    bad = [b for b in blocks if _block_failure(b)]
    out += ["", "## Failed blocks", ""]
    out += [f"- {_ref(by_name, b.page)}, block {b.ord} ({b.category}): {_block_failure(b)}" for b in bad] or ["- none"]
    fixes = [(b, f) for b in blocks for f in b.fixes]
    out += ["", "## Misprint and print-defect fixes", ""]
    if fixes:
        out += ["| Page | Was | Now |", "|---|---|---|"]
        for b, f in fixes:
            now = f"~~{_cell(f['now'])}~~ reverted: {f['rejected']}" if f.get("rejected") else _cell(f["now"])
            out.append(f"| {_ref(by_name, b.page)} | {_cell(f['was'])} | {now} |")
    else:
        out.append("- none")
    merged = [f"- {_ref(by_name, key.partition(':')[0])}, block {key.partition(':')[2]}: {n}"
              for key, notes in (spans or {}).items() for n in notes]
    out += ["", "## Merged cells", ""] + (merged or ["- none"])
    out += ["", "## Sketches in tables", ""] + ([f"- {n}" for n in sketch_notes] or ["- no discrepancies"])
    out += ["", "## Suspicious words (out of dictionary)", ""]
    if spell and spell.top:
        out += ["| Word | Count | Pages |", "|---|---|---|"]
        out += [f"| {_cell(w)} | {n} | {', '.join(ps[:10])} |" for w, n, ps in spell.top]
    else:
        out.append("- none")
    return "\n".join(out) + "\n"
