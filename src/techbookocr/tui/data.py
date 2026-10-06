"""Read-only probes of state for the TUI panels.

The `state.sqlite` of other books is opened only with `sqlite3.connect("file:...?mode=ro", uri=True)`:
`BookState()` creates the file and takes a write lock, which is forbidden here. Any read
error -> None: the panel shows "—", not a traceback.
"""
from __future__ import annotations

import sqlite3
import statistics
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from techbookocr.library import BookRow, Library

# stage -> (table, status column): layout goes by pages, block stages go by blocks.
# ingest/postproc/assemble are book-level stages without per-item progress.
_STAGE_COL = {"layout": ("pages", "layout_status"), "sketches": ("blocks", "sketches_status"),
              "drafts": ("blocks", "drafts_status"), "consensus": ("blocks", "consensus_status"),
              "arbiter": ("blocks", "arbiter_status")}
# stage -> seconds-per-unit column (median, for ETA). layout_seconds is in pages, the rest in blocks.
_SEC_COL = {"layout": "layout_seconds", "drafts": "b_seconds", "arbiter": "arbiter_seconds"}
_GPU_CMD = ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits"]


def state_path(root: Path, name: str) -> Path:
    """`work/state.sqlite` of book `name` under the library root."""
    return Path(root) / name / "work" / "state.sqlite"


def _ro(path: Path) -> sqlite3.Connection:
    # quote is required: `?`/`#` in a book name would start a URI query/fragment and break mode=ro
    conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def progress_of(path: Path, stage: str) -> tuple[int, int] | None:
    """(done, total) units of stage `stage` in state.sqlite at the path; the stage is not per-item,
    the file is missing or the DB failed -> None. The file is not created."""
    tc = _STAGE_COL.get(stage or "")
    if tc is None:
        return None
    table, col = tc
    try:
        conn = _ro(Path(path))
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            done = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}!='pending'").fetchone()[0]
        finally:
            conn.close()
        return done, total
    except (sqlite3.Error, OSError):
        return None


def progress(root: Path, row: BookRow) -> tuple[int, int] | None:
    """(done, total) units of the current `row.stage`; None if the stage is not per-item
    or state.sqlite is missing/unreadable. The file is not created."""
    return progress_of(state_path(root, row.name), row.stage or "")


def stage_seconds(path: Path) -> dict[str, float]:
    """Seconds per stage from meta `seconds:<stage>` of state.sqlite; failure -> {}."""
    try:
        conn = _ro(Path(path))
        try:
            rows = conn.execute("SELECT key, value FROM meta WHERE key LIKE 'seconds:%'").fetchall()
        finally:
            conn.close()
        return {k.split(":", 1)[1]: float(v) for k, v in rows}
    except (sqlite3.Error, OSError, ValueError):
        return {}


def page_count(path: Path) -> int | None:
    """Number of pages (after spread splitting) in state.sqlite; failure -> None."""
    try:
        conn = _ro(Path(path))
        try:
            return int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def rate_seconds(path: Path, stage: str) -> float | None:
    """Median seconds per stage unit; None if the stage has no seconds column, no file
    or fewer than three values."""
    col = _SEC_COL.get(stage)
    if col is None:
        return None
    table = "pages" if stage == "layout" else "blocks"
    try:
        conn = _ro(Path(path))
        try:
            vals = [r[0] for r in conn.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL")]
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None
    return statistics.median(vals) if len(vals) >= 3 else None


def gpu() -> tuple[int, int, int] | None:
    """(util%, used MiB, total MiB) from nvidia-smi; any failure or parse error -> None."""
    try:
        r = subprocess.run(_GPU_CMD, timeout=3, capture_output=True)
        if r.returncode != 0:
            return None
        vals = [int(p) for p in r.stdout.decode().strip().split(",")]
        return (vals[0], vals[1], vals[2]) if len(vals) == 3 else None
    except Exception:
        # Exception, not just OSError/SubprocessError: an exotic failure inside
        # subprocess.run (e.g. a patched Popen) is also a "probe failure", not a reason to crash the tick.
        return None


def daemon_age(lib: Library) -> float | None:
    """Seconds since meta `daemon_heartbeat`; missing or corrupt value -> None."""
    try:
        ts = lib.get_meta("daemon_heartbeat")
        if not ts:
            return None
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return None
