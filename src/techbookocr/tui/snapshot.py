"""Library state snapshots for the panel (`techbookocr bridge`, protocol v1).

Read-only (except the frame-count cache `scans:<name>`); results are JSON-compatible dicts.
File probes and subprocesses give None or an empty value on any error: the panel shows "—".
Library DB errors (sqlite3.Error from lib.*) are deliberately not caught: the bridge gets them and
replies ok:false.
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from techbookocr.ingest.source import scan_count
from techbookocr.library import BOOK_STATUSES, BookRow, Library
from techbookocr.tui import data

EVENTS = 15
SCANS_BUDGET_S = 0.3        # seconds to spend per snapshot on counting frames of books without a cache
LOG_TAIL_BYTES = 256 * 1024
_DOCKER_CMD = ["docker", "ps", "--filter", "name=^techbookocr-", "--format", "{{.Names}}\t{{.CreatedAt}}"]
_TIME_HEADINGS = ("Time per stage", "Время по этапам")
_ROW = re.compile(r"^\|\s*([a-z_]+)\s*\|\s*(\d+(?:\.\d+)?)\s*\|")


def read_json(path: Path) -> dict | None:
    try:
        v = json.loads(Path(path).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def read_text(path: Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def md_sections(text: str) -> dict[str, list[str]]:
    """Level-2 markdown sections: heading -> lines up to the next `## `."""
    out: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def timings_from_quality(text: str) -> dict[str, float]:
    """Stage seconds from the "Time per stage" table of quality.md (books before meta.timings; older Russian books use a Russian heading)."""
    secs = md_sections(text)
    for h in _TIME_HEADINGS:
        if h in secs:
            out = {}
            for line in secs[h]:
                m = _ROW.match(line)
                if m:
                    out[m.group(1)] = float(m.group(2))
            return out
    return {}


def scans_from_meta(meta: dict) -> int | None:
    """Frame count of a finished book from page_map (page name = 4-digit frame + L/R)."""
    pm = meta.get("page_map")
    if isinstance(pm, list) and pm:
        return len({str(p.get("scan", ""))[:4] for p in pm if isinstance(p, dict)})
    return None


def book_timings(root: Path, name: str, meta: dict | None = None) -> dict[str, float]:
    """Timings of a finished book: meta.json (an already parsed meta may be passed), otherwise quality.md."""
    if meta is None:
        meta = read_json(Path(root) / name / "meta.json") or {}
    t = meta.get("timings")
    if isinstance(t, dict) and t:
        return {k: float(v) for k, v in t.items() if isinstance(v, (int, float))}
    text = read_text(Path(root) / name / "quality.md")
    return timings_from_quality(text) if text else {}


def _mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


# book path -> ((mtime meta.json, mtime quality.md), seconds per frame | None): finished books are not re-read
_RATE_CACHE: dict[str, tuple[tuple[int | None, int | None], float | None]] = {}


def book_rate(root: Path, name: str) -> float | None:
    """Seconds per frame of a finished book; the cache is invalidated by mtime of meta.json and quality.md."""
    d = Path(root) / name
    key = (_mtime(d / "meta.json"), _mtime(d / "quality.md"))
    hit = _RATE_CACHE.get(str(d))
    if hit is not None and hit[0] == key:
        return hit[1]
    meta = read_json(d / "meta.json")
    scans = scans_from_meta(meta) if meta else None
    total = sum(book_timings(root, name, meta or {}).values()) if scans else 0
    rate = total / scans if scans and total > 0 else None
    _RATE_CACHE[str(d)] = (key, rate)
    return rate


def done_rate(root: Path, books: list[BookRow]) -> tuple[float | None, int]:
    """Median seconds per frame over done books with known timings; (None, 0) means no data."""
    rates = [r for b in books if b.status == "done" for r in [book_rate(root, b.name)] if r is not None]
    return (statistics.median(rates), len(rates)) if rates else (None, 0)


def current(root: Path, books: list[BookRow]) -> dict | None:
    """A book in progress: stage, progress, seconds per unit (median), stage ETA."""
    proc = next((b for b in books if b.status == "processing"), None)
    if proc is None:
        return None
    p = data.progress(root, proc)
    med = data.rate_seconds(data.state_path(root, proc.name), proc.stage or "")
    eta = max(0, p[1] - p[0]) * med if (p and med) else None
    return {"name": proc.name, "stage": proc.stage, "progress": list(p) if p else None,
            "s_per_unit": med, "eta_s": eta}


def forecast(lib: Library, books: list[BookRow], cur: dict | None, today: str | None = None) -> dict:
    """Queue forecast: sum of queued frames x median s/frame over finished books + ETA of the current stage."""
    queued = [b for b in books if b.status == "queued"]
    known = [lib.scans(b.name) for b in queued]
    scans = sum(s for s in known if s)
    rate, basis = done_rate(lib.root, books)
    seconds = scans * rate + ((cur or {}).get("eta_s") or 0) if rate is not None else None
    today = today or date.today().isoformat()
    done_today = [b for b in books if b.status == "done" and b.updated_at.startswith(today)]
    return {"queued_books": len(queued), "scans": scans, "unknown_scans": sum(s is None for s in known),
            "seconds": seconds, "s_per_scan": rate, "basis_books": basis,
            "done_today": {"books": len(done_today),
                           "scans": sum(lib.scans(b.name) or 0 for b in done_today)}}


def model_info(run=subprocess.run) -> dict | None:
    """techbookocr-* model container: model key and uptime; no docker / no container -> None."""
    try:
        r = run(_DOCKER_CMD, timeout=3, capture_output=True, text=True)
        lines = r.stdout.strip().splitlines() if r.returncode == 0 else []
        if not lines:
            return None
        name, _, created = lines[0].partition("\t")
        up = None
        try:
            ts = datetime.strptime(created[:25], "%Y-%m-%d %H:%M:%S %z")
            up = (datetime.now(ts.tzinfo) - ts).total_seconds()
        except ValueError:
            pass
        return {"key": name.removeprefix("techbookocr-"), "container": name, "up_s": up}
    except Exception:
        return None


def log_tail(root: Path, lines: int) -> list[str]:
    """Last `lines` lines of daemon.log (reads at most LOG_TAIL_BYTES from the end)."""
    path = Path(root) / "daemon.log"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - LOG_TAIL_BYTES))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-max(0, min(lines, 500)):] if lines > 0 else []


def fill_scans(lib: Library, books: list[BookRow], budget_s: float = SCANS_BUDGET_S) -> None:
    """Fill in frame counts for books added before the cache; at most budget_s per call (at least one book)."""
    t0 = time.monotonic()
    for b in books:
        if time.monotonic() - t0 >= budget_s:
            return
        if not lib.has_scans(b.name):
            lib.set_scans(b.name, None)  # "?" in advance: a crash while reading the file will not loop the snapshots
            lib.set_scans(b.name, scan_count(Path(b.path)))


def snapshot(lib: Library) -> dict:
    books = lib.books()
    fill_scans(lib, [b for b in books if b.status == "queued"])
    counts = {s: 0 for s in BOOK_STATUSES}
    for b in books:
        counts[b.status] = counts.get(b.status, 0) + 1
    items = []
    for b in books:
        p = data.progress(lib.root, b) if b.status == "processing" else None
        items.append({"name": b.name, "status": b.status, "stage": b.stage, "priority": b.priority,
                      "error": b.error, "progress": list(p) if p else None, "scans": lib.scans(b.name)})
    cur = current(lib.root, books)
    g = data.gpu()
    return {
        "daemon": {"alive": lib.daemon_alive(), "state": lib.get_meta("daemon_state") or "never ran",
                   "heartbeat_age_s": data.daemon_age(lib), "run_until": lib.get_meta("run_until")},
        "root": str(lib.root.resolve()),
        "counts": counts,
        "books": items,
        "current": cur,
        "forecast": forecast(lib, books, cur),
        "gpu": {"util": g[0], "used_mib": g[1], "total_mib": g[2]} if g else None,
        "model": model_info(),
        "events": [{"ts": e.ts, "book": e.book, "level": e.level, "message": e.message}
                   for e in reversed(lib.events(EVENTS))],
    }


_ISSUE_HEADINGS = ("Layout failures", "Rejected and failed arbiter answers", "Failed blocks",
                   "Сбои разметки", "Отклонённые и сбойные ответы арбитра", "Сбойные блоки")
_NONE = ("- none", "- нет")
ISSUES_MAX = 200


def issues_from_quality(text: str) -> list[str]:
    """Lines of problem sections of quality.md (without the "none" marker lines)."""
    secs = md_sections(text)
    out = []
    for h in _ISSUE_HEADINGS:
        for line in secs.get(h, []):
            s = line.strip()
            if s.startswith("- ") and s not in _NONE:
                out.append(s[2:])
    return out[:ISSUES_MAX]


def issues_from_state(path: Path) -> list[str]:
    """A book in progress: failed layout pages and rejected/failed blocks from state.sqlite (ro)."""
    try:
        conn = data._ro(Path(path))
        try:
            pages = conn.execute("SELECT name, layout_error FROM pages WHERE layout_status='failed' "
                                 "ORDER BY idx").fetchall()
            blocks = conn.execute("SELECT page, ord, kind, arbiter_status, arbiter_note, arbiter_error FROM blocks "
                                  "WHERE arbiter_status IN ('rejected','failed') ORDER BY page, ord").fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    out = [f"{p['name']}: layout failed — {p['layout_error'] or '—'}" for p in pages]
    out += [f"{b['page']}, block {b['ord']} ({b['kind']}): {b['arbiter_status']}, "
            f"{b['arbiter_note'] or b['arbiter_error'] or '—'}" for b in blocks]
    return out[:ISSUES_MAX]


def book_detail(lib: Library, name: str) -> dict:
    """Book details for the Book screen: in progress, state.sqlite; finished, meta.json and quality.md."""
    from techbookocr.pipeline.state import STAGES

    row = lib.book(name)  # KeyError: the bridge replies ok: false
    out = lib.root / name
    meta = read_json(out / "meta.json") or {}
    qmd = read_text(out / "quality.md")
    sp = data.state_path(lib.root, name)
    has_state = sp.exists()
    timings = data.stage_seconds(sp) if has_state else book_timings(lib.root, name, meta)
    pages = data.page_count(sp) if has_state else meta.get("pages")
    cur_i = STAGES.index(row.stage) if row.status == "processing" and row.stage in STAGES else None
    stages = []
    for i, st in enumerate(STAGES):
        sec = timings.get(st)
        if sec is None and not has_state:
            continue
        prog = data.progress_of(sp, st) if has_state else None
        if cur_i is not None:
            status = "running" if i == cur_i else ("done" if i < cur_i else "pending")
        else:
            status = "done" if sec is not None or (prog and prog[1] and prog[0] == prog[1]) else "pending"
        eta = None
        if status == "running" and prog:
            med = data.rate_seconds(sp, st)
            eta = (prog[1] - prog[0]) * med if med else None
        stages.append({"stage": st, "status": status, "seconds": sec,
                       "s_per_page": round(sec / pages, 1) if sec and pages else None,
                       "progress": list(prog) if prog else None, "eta_s": eta})
    lang = meta.get("lang")
    info = {"name": row.name, "source": row.path, "kind": Path(row.path).suffix.lower().lstrip("."),
            "lang": lang[0] if isinstance(lang, list) and lang else None, "mode": meta.get("mode"),
            "scans": lib.scans(name), "pages": pages, "added_at": row.added_at, "updated_at": row.updated_at,
            "status": row.status, "error": row.error}
    issues = issues_from_quality(qmd) if qmd else (issues_from_state(sp) if has_state else [])
    return {"info": info, "stages": stages, "issues": issues, "quality_md": qmd, "out_dir": str(out.resolve())}
