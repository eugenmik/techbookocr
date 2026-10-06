"""Book processing state: work/state.sqlite — pages, blocks, stage statuses, drafts, decisions."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from techbookocr.config import ConfigError
from techbookocr.models.types import Block

STAGES = ("layout", "sketches", "drafts", "consensus", "arbiter", "postproc", "assemble")
PAGE_CATEGORY = "Page"  # synthetic "whole page" block when layout failed
KIND_BY_CATEGORY = {
    "Text": "text", "Title": "title", "Section-header": "title", "Caption": "caption", "Footnote": "footnote",
    "List-item": "list", "Formula": "formula", "Table": "table", PAGE_CATEGORY: "page",
}
_STATUS_COL = {"sketches": "sketches_status", "drafts": "drafts_status",
               "consensus": "consensus_status", "arbiter": "arbiter_status"}
# Block-stage reset: the SET part of UPDATE. SQLite expressions see the old row values.
_BLOCK_RESET = {
    "sketches": "sketches='[]', sketches_error=NULL, "
                "sketches_status=CASE WHEN category='Table' THEN 'pending' ELSE 'skipped' END",
    "drafts": "text_b=NULL, b_error=NULL, b_seconds=NULL, "
              "drafts_status=CASE WHEN kind IS NULL THEN 'skipped' ELSE 'pending' END",
    "consensus": "decision=NULL, cer_ab=NULL, consensus_status='pending', final=NULL, final_source=NULL",
    "arbiter": "arbiter_text=NULL, arbiter_raw=NULL, arbiter_error=NULL, arbiter_note=NULL, arbiter_seconds=NULL, "
               "arbiter_cer=NULL, arbiter_fixes='[]', fixes='[]', "
               "final=CASE WHEN decision='arbiter' THEN NULL ELSE final END, "
               "final_source=CASE WHEN decision='arbiter' THEN NULL ELSE final_source END, "
               "arbiter_status=CASE WHEN decision='arbiter' THEN 'pending' ELSE 'skipped' END",
}
_UPDATABLE = frozenset({
    "text_a", "image", "parent", "sketches", "sketches_status", "sketches_error", "text_b", "b_error", "b_seconds",
    "drafts_status", "decision", "cer_ab", "consensus_status", "arbiter_text", "arbiter_raw", "arbiter_error",
    "arbiter_note", "arbiter_seconds", "arbiter_cer", "arbiter_fixes", "arbiter_status", "final", "final_source",
    "fixes", "origin",
})
_JSON_COLS = frozenset({"sketches", "arbiter_fixes", "fixes"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pages (
    name TEXT PRIMARY KEY,
    idx INTEGER NOT NULL UNIQUE,
    scan INTEGER NOT NULL,
    side TEXT NOT NULL,
    file TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    blank INTEGER NOT NULL DEFAULT 0,
    layout_status TEXT NOT NULL DEFAULT 'pending',
    layout_error TEXT,
    layout_raw TEXT,
    layout_seconds REAL,
    printed TEXT
);
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page TEXT NOT NULL REFERENCES pages(name),
    ord INTEGER NOT NULL,
    category TEXT NOT NULL,
    kind TEXT,
    x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER,
    text_a TEXT NOT NULL DEFAULT '',
    image TEXT,
    parent INTEGER,
    sketches TEXT NOT NULL DEFAULT '[]',
    sketches_status TEXT NOT NULL DEFAULT 'skipped',
    sketches_error TEXT,
    text_b TEXT,
    b_error TEXT,
    b_seconds REAL,
    drafts_status TEXT NOT NULL DEFAULT 'skipped',
    decision TEXT,
    cer_ab REAL,
    consensus_status TEXT NOT NULL DEFAULT 'pending',
    arbiter_text TEXT,
    arbiter_raw TEXT,
    arbiter_error TEXT,
    arbiter_note TEXT,
    arbiter_seconds REAL,
    arbiter_cer REAL,
    arbiter_fixes TEXT NOT NULL DEFAULT '[]',
    arbiter_status TEXT NOT NULL DEFAULT 'skipped',
    final TEXT,
    final_source TEXT,
    fixes TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL DEFAULT 'dots',
    UNIQUE (page, ord)
);
CREATE INDEX IF NOT EXISTS blocks_page ON blocks(page);
"""


@dataclass(frozen=True)
class PageEntry:
    name: str
    idx: int
    scan: int
    side: str
    file: str  # relative to work/ (or an absolute path — for the reference)
    width: int
    height: int
    blank: bool = False


@dataclass
class PageRow:
    name: str
    idx: int
    scan: int = 0
    side: str = ""
    file: str = ""
    width: int = 1000
    height: int = 1400
    blank: bool = False
    layout_status: str = "done"
    layout_error: str | None = None
    layout_seconds: float | None = None
    printed: str | None = None


@dataclass
class BlockRow:
    id: int
    page: str
    ord: int
    category: str
    kind: str | None = None
    bbox: tuple[int, int, int, int] | None = None
    text_a: str = ""
    image: str | None = None
    parent: int | None = None
    sketches: list[dict] = field(default_factory=list)
    sketches_status: str = "skipped"
    sketches_error: str | None = None
    text_b: str | None = None
    b_error: str | None = None
    b_seconds: float | None = None
    drafts_status: str = "skipped"
    decision: str | None = None
    cer_ab: float | None = None
    consensus_status: str = "pending"
    arbiter_text: str | None = None
    arbiter_raw: str | None = None
    arbiter_error: str | None = None
    arbiter_note: str | None = None
    arbiter_seconds: float | None = None
    arbiter_cer: float | None = None
    arbiter_fixes: list[dict] = field(default_factory=list)
    arbiter_status: str = "skipped"
    final: str | None = None
    final_source: str | None = None
    fixes: list[dict] = field(default_factory=list)
    origin: str = "dots"          # dots | layer — source of draft A (OCR or the text layer)


def _page_row(r: sqlite3.Row) -> PageRow:
    return PageRow(name=r["name"], idx=r["idx"], scan=r["scan"], side=r["side"], file=r["file"], width=r["width"],
                   height=r["height"], blank=bool(r["blank"]), layout_status=r["layout_status"],
                   layout_error=r["layout_error"], layout_seconds=r["layout_seconds"], printed=r["printed"])


def _block_row(r: sqlite3.Row) -> BlockRow:
    d = dict(r)
    bbox = None if d["x1"] is None else (d["x1"], d["y1"], d["x2"], d["y2"])
    for k in ("x1", "y1", "x2", "y2"):
        del d[k]
    for k in _JSON_COLS:
        d[k] = json.loads(d[k])
    return BlockRow(bbox=bbox, **d)


class BookState:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._excluded: dict[str, set] = {}  # items deferred for the pass (in memory, not in the DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new_db = not self.path.exists()
        self.conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)  # autocommit; groups via transaction()
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        if is_new_db:
            self.conn.execute("PRAGMA user_version=1")
        else:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self.conn.execute("PRAGMA user_version=1")
            elif version != 1:
                raise ConfigError(f"state.sqlite schema v{version}, expected v1: delete work/state.sqlite or migrate")
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(blocks)")}
        if "origin" not in cols:      # migration: databases from before the text layer
            self.conn.execute("ALTER TABLE blocks ADD COLUMN origin TEXT NOT NULL DEFAULT 'dots'")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "BookState":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Atomic group of changes; a nested call joins the outer transaction."""
        if self.conn.in_transaction:
            yield self.conn
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # --- pages ---

    def add_pages(self, entries: Iterable[PageEntry]) -> None:
        """Add pages; already known ones (by name) are not changed."""
        with self.transaction() as c:
            known = {r[0] for r in c.execute("SELECT name FROM pages")}
            for e in entries:
                if e.name in known:
                    continue
                c.execute("INSERT INTO pages (name, idx, scan, side, file, width, height, blank) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (e.name, e.idx, e.scan, e.side, e.file, e.width, e.height, int(e.blank)))
                known.add(e.name)

    def remove_pages(self, names: Iterable[str]) -> None:
        """Delete pages together with blocks (in one transaction, blocks before pages — foreign key) and
        reset the book-stage flags: the book must be rebuilt."""
        names = list(names)
        if not names:
            return
        marks = ",".join("?" * len(names))
        with self.transaction() as c:
            c.execute(f"DELETE FROM blocks WHERE page IN ({marks})", names)
            c.execute(f"DELETE FROM pages WHERE name IN ({marks})", names)
            c.execute(f"DELETE FROM meta WHERE key IN ({marks})", [f"render:{n}" for n in names])
            c.execute("DELETE FROM meta WHERE key LIKE 'done:%'")

    def pages(self, layout_status: str | None = None) -> list[PageRow]:
        sql, args = "SELECT * FROM pages", ()
        if layout_status is not None:
            sql, args = sql + " WHERE layout_status=?", (layout_status,)
        rows = [_page_row(r) for r in self.conn.execute(sql + " ORDER BY idx", args)]
        if layout_status == "pending":
            rows = [r for r in rows if r.name not in self._excluded.get("layout", ())]
        return rows

    def page(self, name: str) -> PageRow:
        r = self.conn.execute("SELECT * FROM pages WHERE name=?", (name,)).fetchone()
        if r is None:
            raise KeyError(name)
        return _page_row(r)

    def set_layout(self, page: str, blocks: list[Block], *, status: str, error: str | None = None, raw: str = "",
                   seconds: float = 0.0, images: dict[int, str] | None = None) -> None:
        """Replace a page's blocks with the layout result (atomic). A block's ord is its index in the list."""
        images = images or {}
        with self.transaction() as c:
            # Check page exists first (inside transaction, to avoid FK IntegrityError on block insert)
            r = c.execute("SELECT 1 FROM pages WHERE name=?", (page,)).fetchone()
            if r is None:
                raise KeyError(page)
            c.execute("DELETE FROM blocks WHERE page=?", (page,))
            for i, b in enumerate(blocks):
                kind = KIND_BY_CATEGORY.get(b.category)
                x1, y1, x2, y2 = b.bbox if b.bbox is not None else (None, None, None, None)
                c.execute(
                    "INSERT INTO blocks (page, ord, category, kind, x1, y1, x2, y2, text_a, image, "
                    "drafts_status, sketches_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (page, i, b.category, kind, x1, y1, x2, y2, b.text or "", images.get(i),
                     "pending" if kind else "skipped", "pending" if b.category == "Table" else "skipped"))
            cur = c.execute("UPDATE pages SET layout_status=?, layout_error=?, layout_raw=?, layout_seconds=? "
                            "WHERE name=?", (status, error, raw, seconds, page))
            if cur.rowcount != 1:
                raise KeyError(page)

    def set_page_error(self, page: str, error: str | None) -> None:
        self.conn.execute("UPDATE pages SET layout_error=? WHERE name=?", (error, page))

    def update_page_file(self, name: str, file: str, width: int, height: int) -> None:
        """Assign a rendered PNG to a lazy-ingest page (file == "" → "pages/<name>.png")."""
        cur = self.conn.execute("UPDATE pages SET file=?, width=?, height=? WHERE name=?",
                                (file, width, height, name))
        if cur.rowcount != 1:
            raise KeyError(name)

    def set_printed(self, printed: dict[str, str | None]) -> None:
        with self.transaction() as c:
            for name, value in printed.items():
                c.execute("UPDATE pages SET printed=? WHERE name=?", (value, name))

    # --- blocks ---

    def blocks(self, page: str | None = None) -> list[BlockRow]:
        sql, args = "SELECT blocks.* FROM blocks JOIN pages ON pages.name = blocks.page", ()
        if page is not None:
            sql, args = sql + " WHERE blocks.page=?", (page,)
        return [_block_row(r) for r in self.conn.execute(sql + " ORDER BY pages.idx, blocks.ord", args)]

    def block(self, block_id: int) -> BlockRow:
        r = self.conn.execute("SELECT * FROM blocks WHERE id=?", (block_id,)).fetchone()
        if r is None:
            raise KeyError(block_id)
        return _block_row(r)

    def _pending_where(self, stage: str, kinds: Iterable[str] | None) -> tuple[str, list]:
        col = _STATUS_COL[stage]
        where, args = f"blocks.{col}='pending'", []
        excl = sorted(self._excluded.get(stage, ()))
        if excl:
            where += f" AND blocks.id NOT IN ({','.join('?' * len(excl))})"
            args += excl
        if kinds is not None:
            kinds = sorted(kinds)
            where += f" AND blocks.kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        return where, args

    def pending_blocks(self, stage: str, kinds: Iterable[str] | None = None) -> list[BlockRow]:
        where, args = self._pending_where(stage, kinds)
        sql = ("SELECT blocks.* FROM blocks JOIN pages ON pages.name = blocks.page WHERE " + where
               + " ORDER BY pages.idx, blocks.ord")
        return [_block_row(r) for r in self.conn.execute(sql, args)]

    def pending(self, stage: str, kinds: Iterable[str] | None = None) -> int:
        """How many stage items are still unprocessed (for book stages: 1 — not done, 0 — done)."""
        if stage == "layout":
            return len(self.pages(layout_status="pending"))
        if stage in _STATUS_COL:
            where, args = self._pending_where(stage, kinds)
            return self.conn.execute("SELECT COUNT(*) FROM blocks WHERE " + where, args).fetchone()[0]
        if stage in STAGES:
            return 0 if self.get_meta(f"done:{stage}") else 1
        raise ValueError(f"unknown stage {stage!r}")

    def update_block(self, block_id: int, **fields) -> None:
        bad = set(fields) - _UPDATABLE
        if bad:
            raise ValueError(f"not updatable: {sorted(bad)}")
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = [json.dumps(v, ensure_ascii=False) if k in _JSON_COLS else v for k, v in fields.items()]
        cur = self.conn.execute(f"UPDATE blocks SET {cols} WHERE id=?", (*vals, block_id))
        if cur.rowcount != 1:
            raise KeyError(block_id)

    # --- deferred items: in memory only (for the duration of a pass), nothing is written to the DB ---

    def defer(self, stage: str, item) -> bool:
        """Hide a pending item from the stage until undefer (layout: page name, otherwise block id). True if it was pending."""
        if stage == "layout":
            ok = self.conn.execute("SELECT 1 FROM pages WHERE name=? AND layout_status='pending'",
                                   (str(item),)).fetchone()
            item = str(item)
        elif stage in _STATUS_COL:
            ok = self.conn.execute(f"SELECT 1 FROM blocks WHERE id=? AND {_STATUS_COL[stage]}='pending'",
                                   (int(item),)).fetchone()
            item = int(item)
        else:
            raise ValueError(f"stage {stage!r} has no items")
        if ok:
            self._excluded.setdefault(stage, set()).add(item)
        return bool(ok)

    def undefer(self, stage: str, item) -> None:
        self._excluded.get(stage, set()).discard(item if stage == "layout" else int(item))

    def clear_deferred(self) -> None:
        self._excluded.clear()

    def restore_deferred(self) -> None:
        """Safety net: status 'deferred' from an old DB (hard interruption of a previous version) → pending."""
        self.conn.execute("UPDATE pages SET layout_status='pending' WHERE layout_status='deferred'")
        for col in _STATUS_COL.values():
            self.conn.execute(f"UPDATE blocks SET {col}='pending' WHERE {col}='deferred'")

    def transport_pending(self, stage: str) -> list:
        """Items left pending because of a transport failure (the error text starts with "transport:")."""
        if stage == "layout":
            rows = self.conn.execute("SELECT name FROM pages WHERE layout_status='pending' AND layout_error "
                                     "LIKE 'transport:%' ORDER BY idx")
        else:
            err = {"sketches": "sketches_error", "drafts": "b_error", "arbiter": "arbiter_error"}[stage]
            rows = self.conn.execute(f"SELECT blocks.id FROM blocks JOIN pages ON pages.name=blocks.page WHERE "
                                     f"blocks.{_STATUS_COL[stage]}='pending' AND blocks.{err} LIKE 'transport:%' "
                                     "ORDER BY pages.idx, blocks.ord")
        return [r[0] for r in rows]

    def skip_pending(self, stage: str) -> None:
        col = _STATUS_COL[stage]
        self.conn.execute(f"UPDATE blocks SET {col}='skipped' WHERE {col}='pending'")

    # --- reset ---

    def reset_stage(self, stage: str) -> None:
        """Recompute the stage and all following ones (--redo)."""
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        with self.transaction() as c:
            stage_idx = STAGES.index(stage)
            for s in STAGES[stage_idx:]:
                if s == "layout":
                    c.execute("DELETE FROM blocks")
                    c.execute("UPDATE pages SET layout_status='pending', layout_error=NULL, layout_raw=NULL, "
                              "layout_seconds=NULL, printed=NULL")
                elif s in _BLOCK_RESET:
                    if s == "sketches":
                        c.execute("UPDATE blocks SET parent=NULL")
                    c.execute(f"UPDATE blocks SET {_BLOCK_RESET[s]}")
                else:
                    c.execute("DELETE FROM meta WHERE key=?", (f"done:{s}",))
                    if s == "postproc":
                        c.execute("UPDATE pages SET printed=NULL")
            # Clear done:* flags for stages at or after the reset stage
            done_keys = [f"done:{STAGES[i]}" for i in range(stage_idx, len(STAGES))]
            if done_keys:
                marks = ",".join("?" * len(done_keys))
                c.execute(f"DELETE FROM meta WHERE key IN ({marks})", done_keys)
            for s in STAGES[stage_idx:]:
                c.execute("DELETE FROM meta WHERE key LIKE ?", (f"abort:{s}%",))

    def reset_items(self, stage: str, items: Iterable) -> None:
        """Return stage items to pending: page names for layout, block ids for block stages."""
        items = list(items)
        if not items:
            return
        marks = ",".join("?" * len(items))
        with self.transaction() as c:
            if stage == "layout":
                c.execute(f"DELETE FROM blocks WHERE page IN ({marks})", items)
                c.execute("UPDATE pages SET layout_status='pending', layout_error=NULL, layout_raw=NULL, "
                          f"layout_seconds=NULL, printed=NULL WHERE name IN ({marks})", items)
            elif stage in _BLOCK_RESET:
                if stage == "sketches":
                    c.execute(f"UPDATE blocks SET parent=NULL WHERE parent IN ({marks})", items)
                c.execute(f"UPDATE blocks SET {_BLOCK_RESET[stage]} WHERE id IN ({marks})", items)
                # Cascade to later stages for these block ids
                stage_idx = STAGES.index(stage)
                for s in STAGES[stage_idx + 1:]:
                    if s in _BLOCK_RESET:
                        if s == "sketches":
                            c.execute(f"UPDATE blocks SET parent=NULL WHERE id IN ({marks})", items)
                        c.execute(f"UPDATE blocks SET {_BLOCK_RESET[s]} WHERE id IN ({marks})", items)
            else:
                raise ValueError(f"stage {stage!r} has no items")
            # Clear done:* flags for stages at or after the reset stage
            stage_idx = STAGES.index(stage)
            done_keys = [f"done:{STAGES[i]}" for i in range(stage_idx, len(STAGES))]
            if done_keys:
                marks_keys = ",".join("?" * len(done_keys))
                c.execute(f"DELETE FROM meta WHERE key IN ({marks_keys})", done_keys)
            for s in STAGES[stage_idx:]:
                c.execute("DELETE FROM meta WHERE key LIKE ?", (f"abort:{s}%",))

    # --- meta ---

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key: str, value) -> None:
        self.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def mark_done(self, stage: str) -> None:
        self.set_meta(f"done:{stage}", "1")

    def add_seconds(self, stage: str, seconds: float) -> None:
        with self.transaction():
            total = float(self.get_meta(f"seconds:{stage}", "0")) + float(seconds)
            self.set_meta(f"seconds:{stage}", f"{total:.3f}")

    def timings(self) -> dict[str, float]:
        rows = self.conn.execute("SELECT key, value FROM meta WHERE key LIKE 'seconds:%'")
        return {k.split(":", 1)[1]: float(v) for k, v in rows}
