"""Book library: out/library.sqlite holds the book queue, statuses, priorities.

The only module that knows the library.sqlite schema. Per-book progress
(pages/blocks, ETA) is not stored here: it is read from the book's work/state.sqlite.
"""
from __future__ import annotations

import fcntl
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from techbookocr.config import ConfigError

BOOK_STATUSES = ("queued", "processing", "done", "failed", "skipped")
BOOK_SUFFIXES = (".djvu", ".pdf")
COMMANDS = ("pause", "resume", "stop", "skip", "retry", "priority", "run_until")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS books (
    path TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 0,
    stage TEXT, error TEXT,
    added_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL, book TEXT, arg TEXT,
    created_at TEXT NOT NULL, consumed_at TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, book TEXT, level TEXT NOT NULL, message TEXT NOT NULL);
"""


def _now() -> str:
    """Local time, as in run.log."""
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class BookRow:
    path: str          # absolute path to the book file
    name: str          # file stem: unique, the name of the result folder
    status: str        # one of BOOK_STATUSES
    priority: int
    stage: str | None  # current stage (processing only)
    error: str | None
    added_at: str
    updated_at: str


@dataclass(frozen=True)
class AddResult:
    added: list[str]                  # names of accepted books
    skipped: list[tuple[str, str]]    # (path, reason)


@dataclass(frozen=True)
class Command:
    id: int
    command: str        # one of COMMANDS
    book: str | None    # book name, if the command is addressed
    arg: str | None     # argument (e.g. priority)
    created_at: str


@dataclass(frozen=True)
class Event:
    id: int
    ts: str
    book: str | None
    level: str
    message: str


def _book_row(r: sqlite3.Row) -> BookRow:
    return BookRow(**dict(r))


def _command_row(r: sqlite3.Row) -> Command:
    return Command(**dict(r))


def _event_row(r: sqlite3.Row) -> Event:
    return Event(**dict(r))


def expand_inputs(paths: Iterable[Path]) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Arguments of `techbookocr add` -> (books, skipped). Folders are expanded recursively."""
    files: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file():
                    continue  # nested folders were already walked by rglob
                if f.suffix.lower() in BOOK_SUFFIXES:
                    files.append(f)
                else:
                    skipped.append((f, "not a book (.djvu/.pdf)"))
        elif p.is_file() and p.suffix.lower() in BOOK_SUFFIXES:
            files.append(p)
        elif p.exists():
            skipped.append((p, "not a book (.djvu/.pdf)"))
        else:
            skipped.append((p, "no such path"))
    return files, skipped


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "library.sqlite"
        is_new_db = not self.path.exists()
        self.conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)  # autocommit; groups go through transaction()
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        if is_new_db:
            self.conn.execute("PRAGMA user_version=1")
        else:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self.conn.execute("PRAGMA user_version=1")
            elif version != 1:
                raise ConfigError(f"library.sqlite schema v{version}, expected v1: delete {self.path} or migrate")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Library":
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

    # --- queue ---

    def add(self, files: Iterable[Path]) -> AddResult:
        """Add files to the queue; duplicate paths and name collisions go to skipped."""
        added: list[str] = []
        skipped: list[tuple[str, str]] = []
        with self.transaction() as c:
            for f in files:
                f = Path(f)
                path = str(f.resolve())  # absolute: the daemon may run from another cwd
                name = f.stem
                if c.execute("SELECT 1 FROM books WHERE path=?", (path,)).fetchone():
                    skipped.append((str(f), "already in queue"))
                    continue
                if c.execute("SELECT 1 FROM books WHERE name=?", (name,)).fetchone():
                    skipped.append((str(f), f"name {name} already taken"))
                    continue
                now = _now()
                c.execute("INSERT INTO books (path, name, added_at, updated_at) VALUES (?, ?, ?, ?)",
                          (path, name, now, now))
                added.append(name)
        return AddResult(added=added, skipped=skipped)

    def books(self) -> list[BookRow]:
        return [_book_row(r) for r in self.conn.execute("SELECT * FROM books ORDER BY added_at, rowid")]

    def book(self, name: str) -> BookRow:
        r = self.conn.execute("SELECT * FROM books WHERE name=?", (name,)).fetchone()
        if r is None:
            raise KeyError(name)
        return _book_row(r)

    def next_book(self) -> BookRow | None:
        """First queued by priority and time added; rowid breaks added_at ties."""
        r = self.conn.execute("SELECT * FROM books WHERE status='queued' "
                              "ORDER BY priority DESC, added_at, rowid LIMIT 1").fetchone()
        return _book_row(r) if r else None

    def set_status(self, name: str, status: str, *, error: str | None = None, stage: str | None = None) -> None:
        """Change the status; error and stage are always overwritten (None -> NULL)."""
        if status not in BOOK_STATUSES:
            raise ValueError(f"unknown status {status!r}")
        cur = self.conn.execute("UPDATE books SET status=?, error=?, stage=?, updated_at=? WHERE name=?",
                                (status, error, stage, _now(), name))
        if cur.rowcount != 1:
            raise KeyError(name)

    def set_stage(self, name: str, stage: str | None) -> None:
        """Current stage of a processing book; does not touch error."""
        cur = self.conn.execute("UPDATE books SET stage=?, updated_at=? WHERE name=?", (stage, _now(), name))
        if cur.rowcount != 1:
            raise KeyError(name)

    def set_priority(self, name: str, n: int) -> None:
        cur = self.conn.execute("UPDATE books SET priority=?, updated_at=? WHERE name=?", (n, _now(), name))
        if cur.rowcount != 1:
            raise KeyError(name)

    def reset_processing(self) -> list[str]:
        """processing -> queued: books interrupted by the daemon's death return to the queue."""
        with self.transaction() as c:
            names = [r[0] for r in c.execute(
                "SELECT name FROM books WHERE status='processing' ORDER BY added_at, rowid")]
            c.execute("UPDATE books SET status='queued', stage=NULL, updated_at=? "
                      "WHERE status='processing'", (_now(),))
        return names

    # --- commands (CLI/TUI -> daemon IPC) ---

    def push_command(self, command: str, book: str | None = None, arg: str | None = None) -> int:
        """Queue a command for the daemon; returns the row id. An unknown command raises ConfigError."""
        if command not in COMMANDS:
            raise ConfigError(f"unknown command {command!r}, expected one of {COMMANDS}")
        cur = self.conn.execute(
            "INSERT INTO commands (command, book, arg, created_at) VALUES (?, ?, ?, ?)",
            (command, book, arg, _now()))
        return cur.lastrowid

    def poll_commands(self) -> list[Command]:
        """Unconsumed commands, oldest first."""
        return [_command_row(r) for r in self.conn.execute(
            "SELECT id, command, book, arg, created_at FROM commands "
            "WHERE consumed_at IS NULL ORDER BY id")]

    def consume(self, ids: Iterable[int]) -> None:
        """Mark commands as consumed."""
        ids = list(ids)
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        self.conn.execute(f"UPDATE commands SET consumed_at=? WHERE id IN ({marks})",
                          [_now(), *ids])

    def consume_stale(self) -> list[Command]:
        """Consume all pending commands at once; the daemon calls this at startup so it does not run stale ones."""
        with self.transaction() as c:
            stale = [_command_row(r) for r in c.execute(
                "SELECT id, command, book, arg, created_at FROM commands "
                "WHERE consumed_at IS NULL ORDER BY id")]
            c.execute("UPDATE commands SET consumed_at=? WHERE consumed_at IS NULL", (_now(),))
        return stale

    # --- events (daemon journal) ---

    def add_event(self, level: str, message: str, book: str | None = None) -> None:
        self.conn.execute("INSERT INTO events (ts, book, level, message) VALUES (?, ?, ?, ?)",
                          (_now(), book, level, message))

    def events(self, limit: int = 50) -> list[Event]:
        """Latest events, newest first."""
        return [_event_row(r) for r in self.conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    # --- meta (daemon state) ---

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, value))

    def del_meta(self, key: str) -> None:
        self.conn.execute("DELETE FROM meta WHERE key=?", (key,))

    # --- number of book frames (for the panel's forecast) ---

    def set_scans(self, name: str, n: int | None) -> None:
        """Cache of the frame count: meta `scans:<name>`; None -> "?" (counting failed; do not retry)."""
        self.set_meta(f"scans:{name}", str(n) if n is not None else "?")

    def scans(self, name: str) -> int | None:
        v = self.get_meta(f"scans:{name}")
        return int(v) if v and v.isdigit() else None

    def has_scans(self, name: str) -> bool:
        return self.get_meta(f"scans:{name}") is not None

    def heartbeat(self) -> None:
        """A "daemon was alive at this time" mark: informational; liveness is checked by daemon_alive via the lock."""
        self.set_meta("daemon_heartbeat", _now())

    def daemon_alive(self) -> bool:
        """Daemon is alive iff it holds the flock on daemon.lock. The kernel drops the lock even on SIGKILL, no TTL needed."""
        fd = open(self.root / "daemon.lock", "a")  # "a": do not truncate a file held by a live daemon
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            fd.close()
