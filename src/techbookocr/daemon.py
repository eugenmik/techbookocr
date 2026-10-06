"""Library queue daemon: next_book -> run_book loop, commands, heartbeat.

One daemon per library root: DaemonLock holds a flock on daemon.lock.
A failing book is marked failed and does not break the loop; unreadable and broken files
are appended to out_root/library_report.md. daemon_state in meta:
running → paused/stopping → stopped (finally).
"""
from __future__ import annotations

import fcntl
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from techbookocr.config import Config, ConfigError
from techbookocr.library import Library
from techbookocr.models.server import ServerError
from techbookocr.pipeline.control import Control, RunStopped, drain_commands
from techbookocr.pipeline.runner import RunOptions, run_book
from techbookocr.pipeline.transport import StageAborted


class DaemonLock:
    """fcntl lock on <root>/daemon.lock: a second daemon on the same root gets ConfigError."""

    def __init__(self, root: Path):
        self._root = Path(root)
        self._fd = None  # the fd lives on self: closing the file would release the lock

    def __enter__(self) -> "DaemonLock":
        self._root.mkdir(parents=True, exist_ok=True)
        fd = open(self._root / "daemon.lock", "a")  # "a", not "w": do not truncate a file held by a live daemon
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fd.close()
            raise ConfigError("daemon already running")
        self._fd = fd
        return self

    def __exit__(self, *exc) -> None:
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._fd.close()
        self._fd = None


def _note(lib: Library, echo: Callable[[str], None] | None, level: str,
          message: str, book: str | None = None) -> None:
    """Event into the library.sqlite journal and a line on the daemon console."""
    lib.add_event(level, message, book=book)
    if echo:
        echo(f"[{book}] {message}" if book else message)


def run_daemon(lib: Library, cfg: Config, opts: RunOptions, *, out_root: Path,
               run_book_fn: Callable[..., Path] = run_book, deps: dict | None = None,
               summarize_fn: Callable[[Path, str, Config], object] | None = None,
               sleep: Callable[[float], None] = time.sleep,
               echo: Callable[[str], None] | None = print) -> None:
    """Queue loop: queued -> processing -> done/failed/skipped. Returns on the stop command.
    summarize_fn is the summary step after done (auto_summarize); None means techbookocr.summarize.run_summarize."""
    libcfg = cfg.library
    for name in lib.reset_processing():
        lib.add_event("info", "book requeued after daemon restart", book=name)
    for c in lib.consume_stale():
        lib.add_event("info", f"stale command dropped: {c.command}", book=c.book)
    lib.set_meta("daemon_state", "running")
    lib.set_meta("daemon_started_at", datetime.now().isoformat(timespec="seconds"))
    _note(lib, echo, "info", "daemon started")
    try:
        while True:
            lib.heartbeat()
            drain_commands(lib, None)
            while lib.get_meta("daemon_state") == "paused":
                sleep(libcfg.command_poll_s)
                lib.heartbeat()
                drain_commands(lib, None)
            if lib.get_meta("daemon_state") == "stopping":
                return
            run_until = lib.get_meta("run_until")
            if run_until:
                tgt = next((b for b in lib.books() if b.name == run_until), None)
                if tgt is None or tgt.status not in ("queued", "processing"):
                    lib.del_meta("run_until")  # the target vanished or is not running: the flag must not hang forever
                    _note(lib, echo, "warn", f"run_until target {run_until} no longer runnable — cleared")
            row = lib.next_book()
            if row is None:
                sleep(libcfg.idle_poll_s)
                continue
            lib.set_status(row.name, "processing")
            lib.set_stage(row.name, "ingest")  # until the first ctl.set_stage in run_book: ingest, not (None)
            ctl = Control(lib, row.name, poll_s=libcfg.command_poll_s, sleep=sleep)
            try:
                run_book_fn(Path(row.path), out_root, cfg, opts, control=ctl, **(deps or {}))
            except RunStopped as e:
                lib.set_status(row.name, e.outcome)
                _note(lib, echo, "info", f"book interrupted by command → {e.outcome}", book=row.name)
                if lib.get_meta("daemon_state") == "stopping":
                    return
            except (StageAborted, ServerError) as e:
                lib.set_status(row.name, "failed", error=str(e))
                _note(lib, echo, "error", f"book failed: {e}", book=row.name)
            except KeyboardInterrupt:
                lib.set_status(row.name, "queued")  # Ctrl+C: the book stays resumable
                raise
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                lib.set_status(row.name, "failed", error=err)
                _note(lib, echo, "error", f"book failed: {err}", book=row.name)
                with open(out_root / "library_report.md", "a", encoding="utf-8") as f:
                    f.write(f"{row.path} — {err}\n")
            else:
                lib.set_status(row.name, "done", stage=None)
                _note(lib, echo, "info", "book done", book=row.name)
                if libcfg.auto_summarize:
                    try:
                        from techbookocr.summarize import run_summarize
                        (summarize_fn or run_summarize)(out_root, row.name, cfg)
                    except Exception as e:
                        _note(lib, echo, "warn", f"summary failed: {e}", book=row.name)
            if lib.get_meta("run_until") == row.name:
                lib.del_meta("run_until")
                lib.set_meta("daemon_state", "paused")
                _note(lib, echo, "info", "run_until reached — daemon paused", book=row.name)
    finally:
        lib.set_meta("daemon_state", "stopped")
        _note(lib, echo, "info", "daemon stopped")
