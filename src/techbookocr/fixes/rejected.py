"""Shared list of pairs reverted by the user: out/rejected-fixes.json (the library root)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from techbookocr.fixes.journal import write_atomic

REJECTED = "rejected-fixes.json"


def _load(root: Path) -> dict:
    p = root / REJECTED
    if not p.exists():
        return {"version": 1, "pairs": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        raise ValueError("no pairs list")
    for e in data["pairs"]:
        if not (isinstance(e, dict) and isinstance(e.get("was"), str) and isinstance(e.get("now"), str)
                and isinstance(e.get("books"), list) and all(isinstance(b, str) for b in e["books"])):
            raise ValueError(f"bad pair entry: {e!r}")
    return data


def denied_pairs(root: Path, log=lambda m: None) -> frozenset[tuple[str, str]]:
    """(was, now) pairs for the arbiter; a broken or unreadable file gives an empty set and a warning."""
    try:
        return frozenset((str(p["was"]), str(p["now"])) for p in _load(root)["pairs"] if p.get("books"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        log(f"{REJECTED}: ignored ({type(e).__name__}: {e})")
        return frozenset()


def _edit(root: Path, was: str, now: str, book: str, add: bool) -> None:
    p = root / REJECTED
    try:
        data = _load(root)
    except (ValueError, KeyError, TypeError):
        p.rename(p.with_name(f"{REJECTED}.broken-{time.strftime('%Y%m%d-%H%M%S')}"))
        data = {"version": 1, "pairs": []}
    pairs = data["pairs"]
    entry = next((e for e in pairs if e.get("was") == was and e.get("now") == now), None)
    if add:
        if entry is None:
            pairs.append({"was": was, "now": now, "books": [book]})
        elif book not in entry["books"]:
            entry["books"].append(book)
    elif entry is not None:
        entry["books"] = [b for b in entry["books"] if b != book]
        if not entry["books"]:
            pairs.remove(entry)
    write_atomic(p, json.dumps(data, ensure_ascii=False, indent=1))


def add_rejection(root: Path, was: str, now: str, book: str) -> None:
    _edit(root, was, now, book, True)


def remove_rejection(root: Path, was: str, now: str, book: str) -> None:
    _edit(root, was, now, book, False)
