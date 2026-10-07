"""techbookocr-tui panel bridge: JSON lines over stdin/stdout, protocol v1.

The first line is {"ready": true, "v": 1, "root", "config"}; then for each request
{"id", "op", ...} exactly one line {"id", "ok": true, "data"} or {"id", "ok": false, "error"}.
The protocol is written to a duplicate of fd 1; fd 1 and sys.stdout go to stderr, so stray output
(print, C extensions) does not break the protocol. An operation exception is a reply with ok: false, the bridge lives on.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Callable, TextIO

from techbookocr.config import ConfigError, load_config
from techbookocr.library import Library
from techbookocr.tui import actions, snapshot
from techbookocr.tui.settings_io import field_list, save_settings

PROTOCOL = 1


class OpError(Exception):
    """Operation error with ready-made text for the panel."""


class Bridge:
    def __init__(self, root: Path, config_path: Path | None):
        self.toml = Path(config_path) if config_path else Path("techbookocr.toml")
        self.cfg = load_config(config_path)
        self.lib = Library(Path(root))

    def handle(self, req: dict) -> dict:
        rid = req.get("id")
        op = req.get("op")
        fn = _OPS.get(op)
        if fn is None:
            return {"id": rid, "ok": False, "error": f"unknown op {op}"}
        try:
            with contextlib.redirect_stdout(sys.stderr):
                return {"id": rid, "ok": True, "data": fn(self, req)}
        except OpError as e:
            return {"id": rid, "ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 — any operation error goes to the panel
            return {"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"}

    # --- operations ---

    def op_snapshot(self, req: dict) -> dict:
        return snapshot.snapshot(self.lib)

    def op_book(self, req: dict) -> dict:
        name = str(req.get("name", ""))
        try:
            return snapshot.book_detail(self.lib, name)
        except KeyError:
            raise OpError(f"no book {name}") from None

    def op_act(self, req: dict) -> dict:
        action = req.get("action")
        names = [str(n) for n in req.get("books") or []]
        lib, toml = self.lib, self.toml
        if action in ("skip", "retry"):
            msgs = actions.books_command(lib, action, names)
        elif action == "bump":
            msgs = actions.bump(lib, names, int(req.get("delta") or 0))
        elif action == "run":
            msgs = actions.run_books(lib, names, toml)
        elif action == "daemon_start":
            msgs = actions.daemon_start(lib, toml)
        elif action == "daemon_toggle":
            msgs = actions.daemon_toggle(lib)
        elif action == "daemon_stop":
            msgs = actions.daemon_stop(lib)
        else:
            raise OpError(f"unknown action {action}")
        return {"messages": msgs}

    def op_add(self, req: dict) -> dict:
        return actions.add_paths(self.lib, [Path(p) for p in req.get("paths") or []])

    def _library_for(self, cfg) -> Library | None:
        """New library if library.dir in the config changed (not merely differs from --out)."""
        if cfg.library.dir == self.cfg.library.dir:
            return None
        new_root = Path(cfg.library.dir).expanduser()
        if new_root.resolve() == self.lib.root.resolve():
            return None
        return Library(new_root)  # new one first, then close the old one

    def _adopt(self, cfg, new_lib: Library | None) -> None:
        self.cfg = cfg
        if new_lib is not None:
            self.lib.close()
            self.lib = new_lib

    def op_settings_get(self, req: dict) -> dict:
        """The file is re-read: an edit in $EDITOR is visible at once; a broken file is an error, not stale values."""
        try:
            cfg = load_config(self.toml)
        except (ConfigError, tomllib.TOMLDecodeError) as e:
            raise OpError(f"{self.toml.name}: {e}") from None
        self._adopt(cfg, self._library_for(cfg))
        return {"path": str(self.toml.resolve()), "root": str(self.lib.root.resolve()),
                "fields": field_list(self.toml, self.cfg)}

    def op_settings_set(self, req: dict) -> dict:
        updates = {(u["section"], u["key"]): u["value"] for u in req.get("updates") or []}
        before = self.toml.read_text(encoding="utf-8") if self.toml.exists() else None
        try:
            save_settings(self.toml, updates)
            cfg = load_config(self.toml)
            new_lib = self._library_for(cfg)
        except Exception as e:  # noqa: BLE001 — any failure: the file stays as it was, the bridge lives
            if before is not None:
                self.toml.write_text(before, encoding="utf-8")
            else:
                self.toml.unlink(missing_ok=True)
            if isinstance(e, ConfigError):
                raise OpError(str(e)) from None
            raise
        self._adopt(cfg, new_lib)
        return {"root": str(self.lib.root.resolve())}

    def op_log_tail(self, req: dict) -> dict:
        return {"lines": snapshot.log_tail(self.lib.root, int(req.get("lines") or 200))}

    # --- arbiter fixes (fixes.json journal) ---

    def _book_dir(self, req: dict) -> Path:
        name = str(req.get("book", ""))
        d = self.lib.root / name
        if not name or not (d / "book.md").exists():
            raise OpError(f"no assembled book {name}")
        return d

    def _journal_opts(self) -> dict:
        """Library root and dictionary for building the journal of an older book (any call may be the first one)."""
        from techbookocr.pipeline.postproc.spell import load_speller

        p = self.cfg.pipeline
        factory = (lambda langs: load_speller(langs, Path(p.dict_dir).expanduser())) \
            if p.fix_reject_dictionary_words else None
        return {"library_root": self.lib.root, "speller_factory": factory, "dict_min_len": p.fix_dictionary_min_len}

    def op_fixes(self, req: dict) -> dict:
        """The book's fix journal. A book in progress is read-only (peek_journal, no files are written)."""
        from techbookocr.fixes.review import check_editable, load_journal, peek_journal

        d = self._book_dir(req)
        why = check_editable(d, self.lib.root)
        j = peek_journal(d) if why else load_journal(d, **self._journal_opts())
        # out_dir is the absolute book folder: the panel opens a fix's scan crop from it (the v key)
        return {"fixes": [f.to_dict() for f in j.fixes], "counts": j.counts(), "editable": why is None,
                "why_not": why, "out_dir": str(d.resolve())}

    def _fix_reply(self, j, fix_id: str) -> dict:
        return {"fix": j.get(fix_id).to_dict(), "counts": j.counts()}

    def op_fix_set(self, req: dict) -> dict:
        from techbookocr.fixes.review import FixError, set_fix

        d, fid = self._book_dir(req), str(req.get("fix", ""))
        try:
            return self._fix_reply(set_fix(d, fid, bool(req.get("applied")), **self._journal_opts()), fid)
        except (FixError, KeyError) as e:
            raise OpError(f"{fid}: {e}") from None

    def op_fix_keep(self, req: dict) -> dict:
        from techbookocr.fixes.review import FixError, keep_fix

        d, fid = self._book_dir(req), str(req.get("fix", ""))
        try:
            return self._fix_reply(keep_fix(d, fid, **self._journal_opts()), fid)
        except (FixError, KeyError) as e:
            raise OpError(f"{fid}: {e}") from None


_OPS: dict[str, Callable[[Bridge, dict], dict]] = {
    "snapshot": Bridge.op_snapshot, "book": Bridge.op_book, "act": Bridge.op_act, "add": Bridge.op_add,
    "settings_get": Bridge.op_settings_get, "settings_set": Bridge.op_settings_set,
    "log_tail": Bridge.op_log_tail, "fixes": Bridge.op_fixes, "fix_set": Bridge.op_fix_set,
    "fix_keep": Bridge.op_fix_keep,
}


def _write(out: TextIO, msg: dict) -> None:
    line = json.dumps(msg, ensure_ascii=False)  # before writing: a serialization failure does not leave half a line
    out.write(line + "\n")
    out.flush()


def serve(bridge: Bridge, stdin: TextIO, out: TextIO) -> int:
    """Request loop until stdin EOF. An unreadable line gets a reply ok: false with id None."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request must be an object")
        except ValueError as e:
            _write(out, {"id": None, "ok": False, "error": f"bad request: {e}"})
            continue
        reply = bridge.handle(req)
        try:
            _write(out, reply)
        except (TypeError, ValueError) as e:  # data is not serializable: an error reply, the bridge lives
            _write(out, {"id": reply.get("id"), "ok": False, "error": f"cannot serialize reply: {e}"})
    return 0


def serve_stdio(root: Path, config_path: Path | None) -> int:
    out = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        bridge = Bridge(root, config_path)
    except Exception as e:  # noqa: BLE001 — broken config/DB: the panel will show the text
        _write(out, {"ready": False, "v": PROTOCOL, "error": f"{type(e).__name__}: {e}"})
        return 2
    _write(out, {"ready": True, "v": PROTOCOL, "root": str(bridge.lib.root.resolve()),
                 "config": str(bridge.toml.resolve()) if config_path else None})
    try:
        return serve(bridge, sys.stdin, out)
    finally:
        bridge.lib.close()
