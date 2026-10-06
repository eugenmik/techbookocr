"""Polling of daemon commands between model requests.

Control.poll() is called by TransportGuard between model calls,
drain_commands by the daemon's outer loop. RunStopped is the only
exception that propagates outward: a failure to apply a command is written to events, and the command
is still considered consumed.
"""
from __future__ import annotations

import time

from techbookocr.library import Command, Library


class RunStopped(Exception):
    """The book is asked to stop: outcome 'queued' (stop, can be resumed) or 'skipped'."""

    def __init__(self, outcome: str):
        super().__init__(outcome)
        self.outcome = outcome


def _info(lib: Library, cmd: Command) -> None:
    target = f" → {cmd.book}" if cmd.book else ""
    lib.add_event("info", f"command {cmd.command}{target}", book=cmd.book)


def _err(lib: Library, cmd: Command, msg: str) -> None:
    lib.add_event("error", f"command {cmd.command}: {msg}", book=cmd.book)


def apply_command(lib: Library, cmd: Command, current_book: str | None) -> bool:
    """Apply a command; True means cmd requires skipping current_book (skip for it)."""
    if cmd.command == "pause":
        lib.set_meta("daemon_state", "paused")
    elif cmd.command == "resume":
        lib.set_meta("daemon_state", "running")
    elif cmd.command == "stop":
        lib.set_meta("daemon_state", "stopping")
    elif cmd.command == "skip":
        if cmd.book == current_book:
            _info(lib, cmd)
            return True
        row = lib.book(cmd.book)  # KeyError → caught outside by drain_commands
        if row.status != "queued":
            _err(lib, cmd, f"{cmd.book} is {row.status}, skip works only from queued")
            return False
        lib.set_status(cmd.book, "skipped")
    elif cmd.command == "retry":
        row = lib.book(cmd.book)
        if row.status not in ("failed", "skipped"):
            _err(lib, cmd, f"{cmd.book} is {row.status}, retry works only from failed/skipped")
            return False
        lib.set_status(cmd.book, "queued")  # error and stage are reset by set_status
    elif cmd.command == "priority":
        try:
            n = int(cmd.arg)  # type: ignore[arg-type]  # None → TypeError → event
        except (TypeError, ValueError):
            _err(lib, cmd, f"bad arg {cmd.arg!r} for {cmd.book}")
            return False
        lib.set_priority(cmd.book, n)
    elif cmd.command == "run_until":
        if not cmd.book:
            _err(lib, cmd, "run_until needs a book")
            return False
        row = lib.book(cmd.book)  # KeyError → caught outside by drain_commands
        if row.status not in ("queued", "processing"):
            _err(lib, cmd, f"{cmd.book} is {row.status}, run_until works only from queued/processing")
            return False
        lib.set_meta("run_until", cmd.book)  # the daemon will pause after this book
    else:
        _err(lib, cmd, f"unknown command {cmd.command!r}")
        return False
    _info(lib, cmd)
    return False


def drain_commands(lib: Library, current_book: str | None) -> bool:
    """Process all pending commands; True if among them is a skip for current_book."""
    skip = False
    for cmd in lib.poll_commands():
        try:
            skip |= apply_command(lib, cmd, current_book)
        except RunStopped:
            raise
        except Exception as e:
            lib.add_event("error", f"command {cmd.command} (book {cmd.book}): {e}", book=cmd.book)
        lib.consume([cmd.id])
    return skip


class Control:
    """Bridge pipeline ↔ command queue: set_stage + polling throttled by poll_s."""

    def __init__(self, lib: Library, book: str, *, poll_s: float, sleep=time.sleep):
        self._lib = lib
        self._book = book
        self._poll_s = poll_s
        self._sleep = sleep
        self._last: float | None = None

    def set_stage(self, stage: str) -> None:
        self._lib.set_stage(self._book, stage)

    def poll(self) -> None:
        """Heartbeat + command processing; while paused waits for resume/stop. Raises only RunStopped."""
        now = time.monotonic()
        if self._last is not None and now - self._last < self._poll_s:
            return
        self._last = now
        lib = self._lib
        lib.heartbeat()
        skip = drain_commands(lib, self._book)
        while lib.get_meta("daemon_state") == "paused":
            self._sleep(self._poll_s)
            lib.heartbeat()
            skip |= drain_commands(lib, self._book)
        if lib.get_meta("daemon_state") == "stopping":
            raise RunStopped("queued")
        if skip:
            raise RunStopped("skipped")
