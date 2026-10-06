"""Panel actions over the library: commands to books and the daemon, adding books.

Carried over from the former Textual panel without behavior changes. Each returns lines for
panel notifications and never raises: a DB or lock failure is a message, not an exception.
A live daemon gets the command in the queue; a dead one: the command is applied at once (apply_command).
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from techbookocr.library import Command, Library, expand_inputs
from techbookocr.pipeline.control import apply_command

StartFn = Callable[[Library, Path], str]


def book_action(lib: Library, command: str, name: str, arg: str | None = None) -> str:
    """A command on a book -> notification text; the outcome for a dead daemon is checked by status."""
    try:
        if lib.daemon_alive():
            lib.push_command(command, book=name, arg=arg)
            return f"command {command} {name} queued"
        cmd = Command(id=-1, command=command, book=name, arg=arg,
                      created_at=datetime.now().isoformat(timespec="seconds"))
        lib.book(name)  # no such book -> KeyError before apply_command
        apply_command(lib, cmd, None)
        row = lib.book(name)
        want = {"skip": "skipped", "retry": "queued"}.get(command)
        if want is not None and row.status != want:
            return f"{command} {name} rejected: book is {row.status}"
        if command == "priority":
            return f"{name}: priority {row.priority}"
        return f"{command} {name} → {row.status}"
    except KeyError:
        return f"no book {name}"
    except Exception as e:  # DB/lock failure: a message, the panel does not crash
        return f"error {command} {name}: {e}"


def books_command(lib: Library, command: str, names: list[str]) -> list[str]:
    """skip/retry over a list of books."""
    return [book_action(lib, command, n) for n in names]


def bump(lib: Library, names: list[str], delta: int) -> list[str]:
    """Priority +/-delta from each book's current one."""
    out = []
    for name in names:
        try:
            cur = lib.book(name).priority
        except KeyError:
            out.append(f"no book {name}")
            continue
        except Exception as e:
            out.append(f"error priority {name}: {e}")
            return out
        out.append(book_action(lib, "priority", name, str(cur + delta)))
    return out


def start_daemon(lib: Library, config_path: Path, *, python: str = sys.executable, wait_s: float = 2.5,
                 sleep=time.sleep, popen=subprocess.Popen) -> str:
    """`python -m techbookocr daemon --out <root> --config <toml>`, output -> daemon.log.

    --config is always absolute: otherwise the daemon would read ./techbookocr.toml from its own cwd. Popen does not raise
    on a broken config, so after wait_s we check the lock: if it died at once, say so honestly."""
    log_path = lib.root / "daemon.log"
    try:
        if lib.daemon_alive():
            return "daemon already running"
        argv = [python, "-m", "techbookocr", "daemon", "--out", str(lib.root.resolve()),
                "--config", str(Path(config_path).resolve())]
        with open(log_path, "a", encoding="utf-8") as log:
            popen(argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + wait_s
        while True:
            if lib.daemon_alive():
                return f"daemon started, log: {log_path}"
            if time.monotonic() >= deadline:
                return f"daemon failed to start — see {log_path}"
            sleep(0.25)
    except Exception as e:
        return f"daemon not started: {e}"


def run_books(lib: Library, names: list[str], config_path: Path, start: StartFn | None = None) -> list[str]:
    """Run: failed/skipped -> retry, priority above the queue, run_until to the last; a dead daemon is started."""
    start = start or (lambda l, c: start_daemon(l, c))
    if not names:
        return ["select a book first — cursor or space to mark"]
    try:
        books = {b.name: b for b in lib.books()}
        top = max((b.priority for b in books.values() if b.status == "queued"), default=0)
        alive = lib.daemon_alive()
        state = lib.get_meta("daemon_state") or ""
    except Exception as e:
        return [f"error run: {e}"]
    out: list[str] = []
    moved, proc = [], []
    for name in names:
        row = books.get(name)
        if row is None:
            out.append(f"no book {name}")
            continue
        if row.status == "done":
            continue
        if row.status == "processing":
            proc.append(name)  # already running: leave its priority, the target for run_until
            continue
        if row.status in ("failed", "skipped"):
            book_action(lib, "retry", name)
        top += 1
        book_action(lib, "priority", name, str(top))
        moved.append(name)
    if not moved and not proc:
        return out + ["nothing to run — selected books are done"]
    target = moved[-1] if moved else proc[-1]
    book_action(lib, "run_until", target)  # the daemon will pause after the target
    if alive and state == "paused":
        lib.push_command("resume")
    if not alive:
        out.append(start(lib, Path(config_path)))
    n = len(moved) + len(proc)
    what = target if n == 1 else f"{n} books, pause after {target}"
    tail = "daemon starting" if not alive else ("resuming" if state == "paused" else "queued")
    return out + [f"{what} → {tail}"]


def daemon_start(lib: Library, config_path: Path, start: StartFn | None = None) -> list[str]:
    """Start = the whole queue: run_until is cleared; live paused -> resume; live running -> a message."""
    start = start or (lambda l, c: start_daemon(l, c))
    try:
        lib.del_meta("run_until")
        if lib.daemon_alive():
            if lib.get_meta("daemon_state") == "paused":
                lib.push_command("resume")
                return ["daemon resumed — running full queue"]
            return ["daemon already running"]
    except Exception as e:
        return [f"error: {e}"]
    return [start(lib, Path(config_path))]


def daemon_toggle(lib: Library) -> list[str]:
    """paused -> resume, running -> pause; in stopping/stopped no command is written (otherwise the daemon would "park")."""
    try:
        if not lib.daemon_alive():
            return ["daemon is not running"]
        state = lib.get_meta("daemon_state")
        if state not in ("paused", "running"):
            return [f"daemon is {state or '—'}: pause/resume unavailable"]
        command = "resume" if state == "paused" else "pause"
        lib.push_command(command)
        return [f"command {command} queued"]
    except Exception as e:
        return [f"error: {e}"]


def daemon_stop(lib: Library) -> list[str]:
    try:
        if not lib.daemon_alive():
            return ["daemon is not running"]
        lib.push_command("stop")
        return ["command stop queued"]
    except Exception as e:
        return [f"error: {e}"]


SKIPPED_SHOWN = 20  # how many refusals to give the panel; the rest as a count in skipped_total


def add_paths(lib: Library, paths: list[Path]) -> dict:
    """Files and folders -> queue. The frame count is not computed here (hundreds of books would not fit the request
    timeout): the panel snapshot (snapshot.fill_scans) fills it in within a time budget."""
    try:
        files, rejected = expand_inputs([Path(p) for p in paths])
        res = lib.add(files)
        skipped = [[str(p), r] for p, r in rejected] + [[p, r] for p, r in res.skipped]
        n = len(skipped)
        if res.added and not lib.daemon_alive():
            msg = (f"added: {len(res.added)}, skipped: {n} — daemon is not running; "
                   f"press d to process the queue")
        elif res.added:
            msg = f"added: {len(res.added)}, skipped: {n} — daemon is running, books will be processed in turn"
        else:
            msg = f"added: 0, skipped: {n} — already in queue or not a book"
        return {"added": list(res.added), "skipped": skipped[:SKIPPED_SHOWN], "skipped_total": n,
                "messages": [msg]}
    except Exception as e:
        return {"added": [], "skipped": [], "skipped_total": 0, "messages": [f"not added: {e}"]}
