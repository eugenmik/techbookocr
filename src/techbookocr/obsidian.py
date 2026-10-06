"""Obsidian output: YAML frontmatter for book.md and the entry MOC note <Name>.md.

Pure functions with no dependencies: frontmatter fields are fixed, YAML is assembled
from strings. Plugged into finish_book (pipeline/runner.py); format: spec section 4b.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ANCHOR = re.compile(r"<!--\s*page:\s*(\S+)\s+scan:")      # page anchor from assemble.anchor()
_HEAD = re.compile(r"^(#{1,2})\s+(.+?)\s*$")              # only # and ##; ###+ is not a heading for the table of contents
_NON_WORD = re.compile(r"[^\w\s-]+")                      # slug: everything except letters/digits/_/spaces/hyphens is removed
_SPACES = re.compile(r"\s+")


def slugify(title: str) -> str:
    """Heading slug following Obsidian/GitHub rules: lowercase, punctuation dropped,
    whitespace runs -> one hyphen, leading/trailing hyphens stripped."""
    s = _NON_WORD.sub("", title.lower())
    return _SPACES.sub("-", s).strip("-")


def _field(key: str, v) -> str:
    """A YAML field line; for None/empty value, a bare key without a space (not "None")."""
    return f"{key}: {v}" if v not in (None, "") else f"{key}:"


def _yaml_str(s) -> str:
    """String in double quotes: \\-escaping, quotes, newlines -> spaces."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def frontmatter(meta: dict) -> str:
    """YAML block `---\\n...\\n---\\n\\n` with the key fields of meta.json (spec section 4b).
    title is in double quotes with \\-escaping; author/year are empty for None.
    With meta["summary"], description and keywords are added (filled in by techbookocr summarize)."""
    lang = ", ".join(str(x) for x in meta.get("lang") or [])
    lines = [
        "---",
        f"title: {_yaml_str(meta.get('title') or '')}",
        _field("author", meta.get("author")),
        _field("year", meta.get("year")),
        f"lang: [{lang}]",
        _field("pages", meta.get("pages")),
        "tags: []",
        "type: book-source",
    ]
    summary = meta.get("summary") or {}
    desc = str(summary.get("description") or "").strip()
    if desc:
        lines.append(f"description: {_yaml_str(desc)}")
    kws = [str(k).strip() for k in summary.get("keywords") or [] if str(k).strip()]
    if kws:
        lines.append("keywords: [" + ", ".join(_yaml_str(k) for k in kws) + "]")
    lines += ["---", ""]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class TocEntry:
    level: int           # 1 or 2
    title: str           # heading text without # and surrounding spaces
    slug: str            # slugify(title); duplicates give the same slug: a format limitation
    printed: str | None  # printed page of the last anchor before the heading; "?"/none -> None


def toc(md: str) -> list[TocEntry]:
    """#/## headings of book.md in order with the printed page of the last anchor.
    A ``` line toggles a fenced block: headings and anchors inside it do not count."""
    entries: list[TocEntry] = []
    printed: str | None = None
    fenced = False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _ANCHOR.search(line)
        if m:
            printed = m.group(1) if m.group(1) != "?" else None
            continue
        h = _HEAD.match(line)
        if h:
            title = h.group(2)
            entries.append(TocEntry(len(h.group(1)), title, slugify(title), printed))
    return entries


def moc_name(book_name: str) -> str:
    """MOC file name without .md: book/quality get a suffix so service files are not overwritten."""
    return book_name if book_name not in {"book", "quality"} else f"{book_name}-contents"


def moc_note(book_name: str, meta: dict, md: str) -> str:
    """Entry note <Name>.md: frontmatter + links to book.md/quality.md + table of contents.
    md is book.md BEFORE frontmatter is added. Empty contents -> a section without items.
    With meta["summary"]["description"], a preview paragraph goes before the contents."""
    title = str(meta.get("title") or book_name)
    items = []
    for e in toc(md):
        text = e.title.replace("[", "\\[").replace("]", "\\]")  # brackets break the link text
        line = f"- [{text}](book.md#{e.slug})"
        if e.printed:
            line += f" — p. {e.printed}"
        items.append(line)
    lines = [f"# {title}", "", "[Book](book.md) · [Quality report](quality.md)", ""]
    desc = (meta.get("summary") or {}).get("description")
    if desc:
        lines += [str(desc), ""]
    lines += ["## Contents", "", *items]
    return frontmatter(meta) + "\n".join(lines).rstrip("\n") + "\n"
