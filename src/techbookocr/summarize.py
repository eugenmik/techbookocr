"""Book summary: a short description + key terms for preview and navigation in Obsidian.

call(prompt) -> str is injected (in production, make_summarizer: server_for + text chat_image).
Result: meta.json["summary"], a regenerated MOC <Name>.md, out/books-index.md.
book.md is unchanged: the summary lives on the entry note and in the library index.
"""
from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from typing import Callable, Iterator

from techbookocr.config import Config, ConfigError
from techbookocr.obsidian import moc_name, moc_note, toc
from techbookocr.pipeline.assemble import write_text_atomic

EXCERPT_CHARS = 6000   # characters from the start of book.md for the prompt (headings + the beginning of the book)
MAX_TOC = 80           # table-of-contents lines in the prompt
MAX_TOKENS = 1024      # the summary is short: no long tail needed
TEMPERATURE = 0.3
INDEX_NAME = "books-index.md"

_FM = re.compile(r"\A---\n.*?\n---\n\n?", re.S)
_JSON_OBJ = re.compile(r"\{.*\}", re.S)


def strip_frontmatter(md: str) -> str:
    """Strip the leading YAML block of book.md (added at assembly; the content is untouched)."""
    return _FM.sub("", md, count=1)


def collect_signals(book_dir: Path) -> dict:
    """Signals for the summary: meta.json metadata, headings and the start of book.md."""
    meta = json.loads((book_dir / "meta.json").read_text(encoding="utf-8"))
    md = strip_frontmatter((book_dir / "book.md").read_text(encoding="utf-8"))
    return {"title": meta.get("title") or book_dir.name,
            "lang": ",".join(str(x) for x in meta.get("lang") or []),
            "pages": meta.get("pages"),
            "headings": [e.title for e in toc(md)],
            "excerpt": md[:EXCERPT_CHARS]}


def build_prompt(signals: dict) -> str:
    """Model prompt: 2-3 sentences about the book + 5-15 terms, strictly JSON reply."""
    toc_lines = "\n".join(f"- {h}" for h in signals["headings"][:MAX_TOC]) or "(table of contents not extracted)"
    return (
        "You are given a description of a recognized technical book. Write:\n"
        "1) description: a short description of the book in 2-3 sentences: what it is about, which topics "
        "it covers, why to open it;\n"
        "2) keywords: 5-15 key terms of the book (nouns and noun phrases in the nominative case).\n"
        "Write both in the language of the book (given below), e.g. Russian for a Russian book.\n"
        "Reply strictly as JSON of the form {\"description\": \"...\", \"keywords\": [\"...\"]}, with no explanations.\n\n"
        f"Title: {signals['title']}\n"
        f"Language: {signals['lang']}; pages: {signals['pages']}\n\n"
        f"Table of contents:\n{toc_lines}\n\n"
        f"Start of the text:\n{signals['excerpt']}")


def parse_summary(text: str) -> dict:
    """Model reply -> {"description", "keywords", "parsed"}.
    The whole JSON or the first {...}; if it does not parse, description = the whole text, parsed=False."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_OBJ.search(text)
        data = None
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        if not isinstance(data, dict):
            return {"description": text.strip(), "keywords": [], "parsed": False}
    desc = str(data.get("description") or "").strip()
    kws = [str(k).strip() for k in data.get("keywords") or [] if str(k).strip()]
    if not desc:
        return {"description": text.strip(), "keywords": kws, "parsed": False}
    return {"description": desc, "keywords": kws, "parsed": True}


def write_summary(book_dir: Path, summary: dict) -> None:
    """meta.json += summary, the MOC is regenerated with the description; book.md is untouched."""
    meta = json.loads((book_dir / "meta.json").read_text(encoding="utf-8"))
    meta["summary"] = {"description": summary["description"], "keywords": summary["keywords"]}
    md = strip_frontmatter((book_dir / "book.md").read_text(encoding="utf-8"))
    write_text_atomic(book_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    write_text_atomic(book_dir / f"{moc_name(book_dir.name)}.md", moc_note(book_dir.name, meta, md))


def summarize_book(book_dir: Path, call: Callable[[str], str]) -> dict:
    """One model run -> summary written to the book. Returns the summary (with the parsed field)."""
    summary = parse_summary(call(build_prompt(collect_signals(book_dir))))
    write_summary(book_dir, summary)
    return summary


@contextlib.contextmanager
def make_summarizer(cfg: Config) -> Iterator[Callable[[str], str]]:
    """Production call function: pipeline.summarizer_model container + chat_image without an image."""
    from openai import OpenAI

    from techbookocr.models.server import api_key, server_for
    from techbookocr.models.vlm import chat_image

    key = cfg.pipeline.summarizer_model
    if key not in cfg.models:
        raise ConfigError(f"[pipeline] summarizer_model {key!r} not found in [models]")
    spec = cfg.models[key]
    with server_for(spec, cfg.server) as server:
        client = OpenAI(base_url=server.base_url, api_key=api_key(spec), max_retries=0)

        def call(prompt: str) -> str:
            text, status = chat_image(client, spec.model, None, prompt,
                                      max_tokens=spec.params.get("max_tokens", MAX_TOKENS),
                                      temperature=spec.params.get("temperature", TEMPERATURE))
            if status in ("bad_request", "repeat_limit"):  # not text but an adapter error code
                raise ConfigError(f"summarizer {key}: {status}: {text[:200]}")
            return text

        yield call


def book_dirs(root: Path) -> list[Path]:
    """Book folders in the library root: directories with meta.json."""
    return sorted(d for d in Path(root).iterdir() if d.is_dir() and (d / "meta.json").exists())


def books_index_text(root: Path) -> str:
    """Library root index: [[MOC note|title]] — summary, one line per book."""
    lines = ["---", "type: books-index", "---", "", "# Library", ""]
    for d in book_dirs(root):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        desc = (meta.get("summary") or {}).get("description") or "—"
        title = meta.get("title") or d.name
        lines.append(f"- [[{moc_name(d.name)}|{title}]] — {desc}")
    return "\n".join(lines) + "\n"


def update_books_index(root: Path) -> Path:
    p = Path(root) / INDEX_NAME
    write_text_atomic(p, books_index_text(root))
    return p


def run_summarize(root: Path, name: str, cfg: Config, *,
                  call: Callable[[str], str] | None = None, redo: bool = False) -> dict | None:
    """Summary of one book in root. Already present and not redo -> None (idempotent). The index is updated."""
    book_dir = Path(root) / name
    if not (book_dir / "meta.json").exists():
        raise ConfigError(f"no meta.json: {book_dir} (the book is not built)")
    meta = json.loads((book_dir / "meta.json").read_text(encoding="utf-8"))
    if meta.get("summary") and not redo:
        return None
    if call is None:
        with make_summarizer(cfg) as c:
            summary = summarize_book(book_dir, c)
    else:
        summary = summarize_book(book_dir, call)
    update_books_index(root)
    return summary
