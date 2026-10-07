"""The book's fix journal (out/<book>/fixes.json) and the "Misprint and print-defect fixes" section of quality.md."""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

JOURNAL = "fixes.json"
STATES = ("applied", "reverted", "not_found")
_HEADING = re.compile(r"^## (Misprint and print-defect fixes|Исправления опечаток.*)$", re.M)
_SUMMARY = re.compile(r"^\| (Misprint fixes|Исправления опечаток) \|.*\|$", re.M)
_PAGE = re.compile(r"^(\S+)(?: \((?:p|с)\. ([^)]+)\))?$")
_REVERTED = re.compile(r"^~~(.*)~~ (?:\*\*reverted\*\*|reverted(?:: (.+))?)$")
_REVIEW = re.compile(r"^(.*) \(review: (.+)\)$")
_NOT_FOUND = " (not found in book.md)"
_SPLIT = re.compile(r"(?<!\\)\|")


class JournalError(ValueError):
    """A broken fixes.json."""


@dataclass
class Fix:
    id: str
    scan: str
    page: str | None
    block: int | None
    kind: str | None
    was: str
    now: str
    state: str
    suggested: bool = False
    reason: str | None = None
    decided_by: str = "model"
    before: str = ""
    after: str = ""
    crop: str | None = None     # scan crop of the block, relative to the book folder ("fixes/0046-b3.webp")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Fix":
        if not isinstance(d, dict):
            raise JournalError(f"bad fix record: {d!r}")
        names = {f.name for f in fields(cls)}
        try:
            fx = cls(**{k: v for k, v in d.items() if k in names})
        except TypeError as e:
            raise JournalError(f"bad fix record: {d!r}") from e
        text = all(isinstance(getattr(fx, n), str) for n in ("id", "scan", "was", "now", "before", "after",
                                                             "decided_by"))
        opt = all(v is None or isinstance(v, t)
                  for v, t in ((fx.page, str), (fx.kind, str), (fx.reason, str), (fx.crop, str)))
        blk = fx.block is None or (isinstance(fx.block, int) and not isinstance(fx.block, bool))
        if not (text and opt and blk and isinstance(fx.suggested, bool)) or fx.state not in STATES:
            raise JournalError(f"bad fix record: {d!r}")
        return fx


@dataclass
class Journal:
    fixes: list[Fix] = field(default_factory=list)
    version: int = 1

    def get(self, fix_id: str) -> Fix:
        for f in self.fixes:
            if f.id == fix_id:
                return f
        raise KeyError(fix_id)

    def counts(self) -> dict[str, int]:
        c = {"applied": 0, "reverted": 0, "suggested": 0, "not_found": 0}
        for f in self.fixes:
            c["suggested" if f.state == "applied" and f.suggested else f.state] += 1
        return c


def _default_mode() -> int:
    """Permissions of a new file, as with a plain open(): 0o666 minus the umask."""
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def write_atomic(path: Path, text: str) -> None:
    """Write via a temporary file and os.replace; an existing file keeps its permissions
    (mkstemp creates 0600), a new one gets them from the umask."""
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = _default_mode()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_journal(path: Path) -> Journal | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("fixes"), list):
            raise JournalError(f"{path}: no fixes list")
        return Journal([Fix.from_dict(d) for d in data["fixes"]], int(data.get("version", 1)))
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as e:
        raise JournalError(f"{path}: {e}") from e


def save_journal(path: Path, journal: Journal) -> None:
    write_atomic(path, json.dumps({"version": journal.version, "fixes": [f.to_dict() for f in journal.fixes]},
                                  ensure_ascii=False, indent=1))


def _section(text: str) -> tuple[int, int] | None:
    """Bounds of the fixes section: from its heading to the next "## " (or the end)."""
    m = _HEADING.search(text)
    if not m:
        return None
    nxt = text.find("\n## ", m.end())
    return m.start(), (nxt + 1 if nxt != -1 else len(text))


def _cells(line: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in _SPLIT.split(line.strip())[1:-1]]


def parse_quality_fixes(text: str) -> list[Fix]:
    """Table rows of the fixes section → Fix. Formats of the "Now" column: plain text; "~~x~~ reverted: reason";
    "~~x~~ **reverted**" (old); "x (review: reason)"; "x (not found in book.md)" (written by our regeneration)."""
    span = _section(text)
    if span is None:
        return []
    out: list[Fix] = []
    per_scan: dict[str, int] = {}
    for line in text[span[0]:span[1]].splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = _cells(line)
        if len(cells) != 3 or cells[0] in ("Page", "Страница"):
            continue
        pm = _PAGE.match(cells[0])
        if not pm:
            continue
        scan, page = pm.group(1), pm.group(2)
        was, now_cell = cells[1], cells[2]
        state, reason, decided, suggested, now = "applied", None, "model", False, now_cell
        if (m := _REVERTED.match(now_cell)):
            now, state, reason, decided = m.group(1), "reverted", m.group(2), "rule"
            if reason == "rejected by user":
                decided = "user"
        elif now_cell.endswith(_NOT_FOUND):
            now, state = now_cell[: -len(_NOT_FOUND)], "not_found"
        elif (m := _REVIEW.match(now_cell)):
            now, reason, suggested = m.group(1), m.group(2), True
        per_scan[scan] = per_scan.get(scan, 0) + 1
        out.append(Fix(id=f"{scan}-{per_scan[scan]}", scan=scan, page=page, block=None, kind=None, was=was,
                       now=now, state=state, suggested=suggested, reason=reason, decided_by=decided))
    return out


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _row(f: Fix) -> str:
    ref = f"{f.scan} (p. {f.page})" if f.page else f.scan
    if f.state == "reverted":
        now = f"~~{_cell(f.now)}~~ reverted" + (f": {f.reason}" if f.reason else "")
    elif f.state == "not_found":
        now = _cell(f.now) + _NOT_FOUND
    elif f.suggested:
        now = f"{_cell(f.now)} (review: {f.reason})"
    else:
        now = _cell(f.now)
    return f"| {ref} | {_cell(f.was)} | {now} |"


def render_fixes_section(quality_text: str, journal: Journal) -> str:
    """quality.md with the fixes section and the summary row regenerated; the rest of the text is unchanged.
    The section heading and the table header row are kept as they were (Russian reports stay Russian)."""
    span = _section(quality_text)
    if span is None:
        head, header = "## Misprint and print-defect fixes", "| Page | Was | Now |"
        start = end = len(quality_text)
        prefix = "\n" if quality_text and not quality_text.endswith("\n\n") else ""
    else:
        start, end = span
        old = quality_text[start:end]
        head = old.splitlines()[0]
        header = next((ln for ln in old.splitlines() if ln.startswith("| ") and _cells(ln)[:1] in (["Page"], ["Страница"])),
                      "| Page | Was | Now |")
        prefix = ""
    body = [header, "|---|---|---|"] + [_row(f) for f in journal.fixes] if journal.fixes else ["- none"]
    tail = "\n" if span is not None and end < len(quality_text) else ""
    section = prefix + "\n".join([head, ""] + body) + "\n" + tail
    text = quality_text[:start] + section + quality_text[end:]
    c = journal.counts()
    applied = c["applied"] + c["suggested"]
    return _SUMMARY.sub(lambda m: f"| {m.group(1)} | {applied} (reverted: {c['reverted']}) |", text, count=1)
