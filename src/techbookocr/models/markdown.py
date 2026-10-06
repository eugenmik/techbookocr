"""Layout blocks -> page Markdown."""
from __future__ import annotations

import re
from typing import Callable

from techbookocr.models.types import Block

_DROP = {"Page-header", "Page-footer"}
_LIST_MARK = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[а-яa-z][.)])\s")


_UNESCAPED_DOLLAR = re.compile(r"(?<!\\)\$")


def _formula(text: str) -> str | None:
    """Formula block -> display math. Empty -> None; a line with several formulas stays text."""
    body = text.strip()
    for left, right in (("$$", "$$"), (r"\[", r"\]"), ("$", "$")):
        if body.startswith(left) and body.endswith(right) and len(body) >= len(left) + len(right):
            inner = body[len(left):-len(right)]
            if _UNESCAPED_DOLLAR.search(inner) or (left == r"\[" and r"\]" in inner):
                return body  # several formulas / mixed with text: keep as a paragraph with inline math
            body = inner.strip()
            break
    return f"$$\n{body}\n$$" if body else None


def _render(block: Block, picture_ref: Callable[[Block], str] | None) -> str | None:
    c, t = block.category, block.text.strip()
    if c in _DROP:
        return None
    if c == "Title":
        return f"# {t.lstrip('#').strip()}"
    if c == "Section-header":
        return t if t.startswith("#") else f"## {t}"
    if c == "List-item":
        return t if _LIST_MARK.match(t) else f"- {t}"
    if c == "Formula":
        return _formula(t)
    if c == "Picture":
        return f"![]({picture_ref(block) if picture_ref else ''})"
    return t or None


def blocks_to_markdown(blocks: list[Block], picture_ref: Callable[[Block], str] | None = None) -> str:
    parts = [p for b in blocks if (p := _render(b, picture_ref))]
    return "\n\n".join(parts) + "\n" if parts else ""
