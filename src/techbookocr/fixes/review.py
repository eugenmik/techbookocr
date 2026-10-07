"""Decisions on a finished book's fixes: toggling "now ⇄ was", "keep", self-healing of the journal."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from techbookocr.fixes.journal import JOURNAL, Fix, Journal, JournalError, parse_quality_fixes, read_journal, \
    render_fixes_section, save_journal, write_atomic
from techbookocr.fixes.locate import context, current, find, locate
from techbookocr.fixes.rejected import add_rejection, denied_pairs, remove_rejection
from techbookocr.pipeline.arbiter import fix_reason
from techbookocr.pipeline.postproc.spell import speller_langs


class FixError(Exception):
    """Refusal to change a fix; the message is shown by the panel and the CLI."""


def check_editable(book_dir: Path, library_root: Path) -> str | None:
    """None if fixes may be changed; otherwise the reason. A book outside the queue (run --out) is free."""
    if not (library_root / "library.sqlite").exists():
        return None
    from techbookocr.library import Library

    with Library(library_root) as lib:
        try:
            row = lib.book(book_dir.name)
        except KeyError:
            return None
    return "book is processing" if row.status == "processing" else None


def _one_sided(f: Fix) -> bool:
    """Empty "was" or "now" (an insertion or a deletion of text): the place of such a fix in the book cannot be found."""
    return not f.was or not f.now


def _lose(f: Fix) -> None:
    """The fix's place is lost: toggling is unavailable, the "?" mark and the context are cleared."""
    f.state, f.suggested, f.before, f.after = "not_found", False, "", ""


def _save(book_dir: Path, journal: Journal) -> None:
    save_journal(book_dir / JOURNAL, journal)
    q = book_dir / "quality.md"
    text = q.read_text(encoding="utf-8") if q.exists() else ""
    write_atomic(q, render_fixes_section(text, journal))


def heal(book_dir: Path, journal: Journal) -> bool:
    """Check the records against book.md. The "current" variant is found: state is right (the context is
    updated if the place was found by token). It is not found at all and the "other" one is found exactly
    once: state follows the text (the process died between writes); if the fix has a context, an exact
    "before + other + after" match is required. An ambiguity or both missing: not_found, someone else's
    text is left alone. Saves the journal and quality.md if anything changed."""
    md = (book_dir / "book.md").read_text(encoding="utf-8")
    changed = False
    for f in journal.fixes:
        if f.state == "not_found":
            continue
        if _one_sided(f):
            _lose(f)
            changed = True
            continue
        got = locate(md, f, current(f))
        has_ctx = bool(f.before or f.after)
        if got.status == "found" and not got.exact and has_ctx:
            # "current" is found only by token, "other" exactly by context: the exact context is more reliable
            # (the token may have hit unrelated identical text), so the book is already in the "other" state
            alt = locate(md, f, f.was if f.state == "applied" else f.now)
            if alt.status == "found" and alt.exact:
                f.state = "reverted" if f.state == "applied" else "applied"
                f.before, f.after = context(md, *alt.span)
                changed = True
                continue
        if got.status == "found":
            if not got.exact:
                ctx = context(md, *got.span)
                if ctx != (f.before, f.after):
                    f.before, f.after = ctx
                    changed = True
            continue
        other = locate(md, f, f.was if f.state == "applied" else f.now) if got.status == "absent" else got
        # the fix has a context: flip only on an exact "before + other + after"; a token without context
        # may point at unrelated text, while a genuine crash between writes leaves the context intact
        if other.status == "found" and (other.exact or not has_ctx):
            f.state = "reverted" if f.state == "applied" else "applied"
            f.before, f.after = context(md, *other.span)
        else:
            _lose(f)
        changed = True
    if changed:
        _save(book_dir, journal)
    return changed


def _book_lang(book_dir: Path) -> str:
    try:
        lang = json.loads((book_dir / "meta.json").read_text(encoding="utf-8")).get("lang")
    except (OSError, json.JSONDecodeError, AttributeError):
        return "ru"
    return lang[0] if isinstance(lang, list) and lang else (lang if isinstance(lang, str) else "ru")


def _from_quality(book_dir: Path) -> Journal:
    q = book_dir / "quality.md"
    return Journal(parse_quality_fixes(q.read_text(encoding="utf-8")) if q.exists() else [])


def _build_legacy(book_dir: Path, library_root: Path, speller_factory, dict_min_len: int, log,
                  apply_rules: bool = True) -> Journal:
    """Journal of an older book from quality.md, with rules applied: unambiguous rules and the user's pairs
    revert, the dictionary rule only sets "?"; places are looked up in book.md (not found: not_found). Only a
    fix found in its own scan's section is reverted automatically; one found only in the next section stays
    as it is. apply_rules=False (rebuild after a broken fixes.json, the rules have already run): parsing and
    locating only."""
    journal = _from_quality(book_dir)
    path = book_dir / "book.md"
    md = path.read_text(encoding="utf-8") if path.exists() else ""
    denied = denied_pairs(library_root, log) if apply_rules else frozenset()
    speller = None
    if apply_rules and speller_factory:
        try:
            speller = speller_factory(speller_langs(_book_lang(book_dir)))
        except Exception as e:          # no dictionary: no "?" marks, the other rules still work
            log(f"speller unavailable ({type(e).__name__}: {e}); no dictionary suggestions")
    for f in journal.fixes:
        if f.state == "not_found":
            continue
        if _one_sided(f):
            _lose(f)
            continue
        got = locate(md, f, current(f))
        flipped = False
        if got.status == "absent":
            # crash window: the book is already in the other state, state follows the text as in heal
            got = locate(md, f, f.was if f.state == "applied" else f.now)
            if got.status == "found":
                f.state = "reverted" if f.state == "applied" else "applied"
                flipped = True
        if got.status != "found":
            _lose(f)
            continue
        loc = got.span
        f.before, f.after = context(md, *loc)
        # a record flipped by the text already carries the earlier decision: no rules and no "?" for it
        if flipped or f.state != "applied" or not apply_rules or not got.own:
            continue
        reason = fix_reason(f.was, f.now, denied=denied)
        if reason:
            md = md[:loc[0]] + f.was + md[loc[1]:]
            f.before, f.after = context(md, loc[0], loc[0] + len(f.was))
            f.state, f.reason, f.suggested = "reverted", reason, False
            f.decided_by = "user" if reason == "rejected by user" else "rule"
        elif speller is not None and fix_reason(f.was, f.now, speller=speller,
                                                dict_min_len=dict_min_len) == "replaces dictionary word":
            f.suggested, f.reason = True, "replaces dictionary word"
    if path.exists() and md != path.read_text(encoding="utf-8"):
        write_atomic(path, md)
    _save(book_dir, journal)
    return journal


def load_journal(book_dir: Path, *, library_root: Path, speller_factory=None, dict_min_len: int = 4,
                 log=lambda m: None) -> Journal:
    """The book's journal: reads fixes.json and heals it against the text; no file: builds it from quality.md
    (an older book). A broken fixes.json is moved to fixes.json.broken-<time> and the journal is rebuilt
    without rules. speller_factory(langs) -> Speller | None."""
    path = book_dir / JOURNAL
    rules = True
    try:
        journal = read_journal(path)
    except JournalError as e:
        log(f"{path}: {e}; rebuilt from quality.md")
        path.rename(path.with_name(f"{JOURNAL}.broken-{time.strftime('%Y%m%d-%H%M%S')}"))
        journal, rules = None, False
    if journal is None:
        return _build_legacy(book_dir, library_root, speller_factory, dict_min_len, log, apply_rules=rules)
    heal(book_dir, journal)
    return journal


def peek_journal(book_dir: Path) -> Journal:
    """The journal without writing any files: for a book in progress (read-only)."""
    try:
        journal = read_journal(book_dir / JOURNAL)
    except JournalError:
        journal = None
    return journal if journal is not None else _from_quality(book_dir)


CROPS = "fixes"            # folder of scan crops in out/<book>/


def _clear_crops(book_dir: Path) -> None:
    """Remove the crops of a previous assembly (--redo): old files must not point at other blocks."""
    d = book_dir / CROPS
    if d.is_symlink() or d.is_file():
        d.unlink()
    elif d.exists():
        shutil.rmtree(d)


def _save_crop(book_dir: Path, b, images, cfg) -> str:
    """Crop of the block from the scan at its original resolution (box + crop_pad, no upscaling); a whole-page
    block or a block without a box gives the whole page, shrunk to [pipeline] fix_page_crop_max. The path is
    relative to the book folder."""
    from PIL import Image

    from techbookocr.pipeline.crops import pad_box, save_image

    page = images.get(b.page)
    bbox = getattr(b, "bbox", None)
    if b.kind == "page" or bbox is None:
        img = page.copy()
        img.thumbnail((cfg.fix_page_crop_max, cfg.fix_page_crop_max), Image.Resampling.LANCZOS)
    else:
        img = page.crop(pad_box(tuple(bbox), page.size, cfg.crop_pad))
    rel = f"{CROPS}/{b.page}-b{b.ord}.webp"
    save_image(img, book_dir / rel, quality=cfg.webp_quality)
    return rel


def journal_from_blocks(book_dir: Path, blocks, pages, *, images=None, cfg=None,
                        log=lambda m: None) -> Journal:
    """Journal of a new book from state (b.fixes with or without the rejected field), built at assembly while
    work/ is still there. Each record's state follows what actually stands in the assembled book.md. A place
    that cannot be found unambiguously (several token occurrences without context) and a fix with an empty
    "was" or "now" give not_found; the other variant is looked up only if the expected one is absent.
    images (PageImages): every block with fixes gets a scan crop in fixes/ (the crop field of its records);
    without images there are no crops. A failed crop goes to log, the block's fixes stay without crop and the
    assembly goes on."""
    if cfg is None:
        from techbookocr.config import PipelineConfig
        cfg = PipelineConfig()
    _clear_crops(book_dir)
    printed = {p.name: p.printed for p in pages}
    md = (book_dir / "book.md").read_text(encoding="utf-8")
    per_scan: dict[str, int] = {}
    out: list[Fix] = []
    for b in blocks:
        crop = None
        if b.fixes and images is not None:
            try:
                crop = _save_crop(book_dir, b, images, cfg)
            except Exception as e:  # noqa: BLE001 — the crop is only for viewing, the journal matters more
                log(f"fix crop {b.page} block {b.ord}: {type(e).__name__}: {e}")
        for raw in b.fixes or []:
            per_scan[b.page] = per_scan.get(b.page, 0) + 1
            rejected = raw.get("rejected")
            f = Fix(id=f"{b.page}-{per_scan[b.page]}", scan=b.page, page=printed.get(b.page), block=b.ord,
                    kind=b.kind, was=str(raw.get("was", "")), now=str(raw.get("now", "")),
                    state="reverted" if rejected else "applied", reason=rejected,
                    decided_by=("user" if rejected == "rejected by user" else "rule") if rejected else "model",
                    crop=crop)
            if _one_sided(f):                 # an insertion or a deletion cannot be found in the book
                _lose(f)
                out.append(f)
                continue
            got = locate(md, f, current(f))
            if got.status == "absent":       # the revert failed (or the fix was not applied): the other variant
                f.state = "applied" if rejected else "reverted"
                got = locate(md, f, current(f))
            # an ambiguous expected variant gives not_found: flipping to the other variant could point at
            # unrelated identical text (a genuine "1/8" next to two printed "1/3")
            if got.status == "found":
                f.before, f.after = context(md, *got.span)
            else:
                _lose(f)
            out.append(f)
    try:                                 # every crop failed after the folder was created: no empty folder left
        (book_dir / CROPS).rmdir()
    except OSError:
        pass
    journal = Journal(out)
    save_journal(book_dir / JOURNAL, journal)
    return journal


def summary(book_dir: Path) -> dict | None:
    """Summary for the book card without building the journal: no fixes.json, the row count in quality.md.
    An unreadable file (permissions, not UTF-8, a directory instead of a file) gives None: the card shows no summary."""
    try:
        try:
            journal = read_journal(book_dir / JOURNAL)
        except JournalError:
            journal = None
        if journal is None:
            return {"total": len(_from_quality(book_dir).fixes), "suggested": None, "reviewed": False}
    except (OSError, ValueError):
        return None
    sug = journal.counts()["suggested"]
    return {"total": len(journal.fixes), "suggested": sug, "reviewed": sug == 0}


def _open(book_dir: Path, library_root: Path, speller_factory, dict_min_len: int) -> Journal:
    why = check_editable(book_dir, library_root)
    if why:
        raise FixError(why)
    return load_journal(book_dir, library_root=library_root, speller_factory=speller_factory,
                        dict_min_len=dict_min_len)


def set_fix(book_dir: Path, fix_id: str, applied: bool, *, library_root: Path, speller_factory=None,
            dict_min_len: int = 4) -> Journal:
    """Set the fix to "now" (applied) or "was". book.md first, then the journal: after a crash between the
    writes the next heal() call repairs state from the book's text. speller_factory and dict_min_len are needed
    if this call is the first to build an older book's journal (otherwise no dictionary "?" marks appear)."""
    journal = _open(book_dir, library_root, speller_factory, dict_min_len)
    fix = journal.get(fix_id)
    if _one_sided(fix):
        raise FixError(f"{fix_id}: fix inserts or deletes text, cannot be toggled")
    if fix.state == "not_found":
        raise FixError(f"{fix_id}: not found in book.md")
    target = "applied" if applied else "reverted"
    if fix.state != target:
        md = (book_dir / "book.md").read_text(encoding="utf-8")
        cur = current(fix)
        loc = find(md, fix, cur)
        if loc is None or md[loc[0]:loc[1]] != cur:
            fix.state, fix.suggested = "not_found", False
            _save(book_dir, journal)
            raise FixError(f"{fix_id}: fix location changed")
        new = fix.now if applied else fix.was
        md = md[:loc[0]] + new + md[loc[1]:]
        write_atomic(book_dir / "book.md", md)
        fix.before, fix.after = context(md, loc[0], loc[0] + len(new))
        fix.state = target
    fix.decided_by, fix.suggested = "user", False
    fix.reason = None if applied else "rejected by user"
    _save(book_dir, journal)
    if applied:
        remove_rejection(library_root, fix.was, fix.now, book_dir.name)
    else:
        add_rejection(library_root, fix.was, fix.now, book_dir.name)
    return journal


def keep_fix(book_dir: Path, fix_id: str, *, library_root: Path, speller_factory=None,
             dict_min_len: int = 4) -> Journal:
    """Keep a suspicious fix: clear the suggested mark, leave the book's text alone. For a fix without "?"
    nothing changes and nothing is written (the model's or the rule's decision stays)."""
    journal = _open(book_dir, library_root, speller_factory, dict_min_len)
    fix = journal.get(fix_id)
    if not fix.suggested:
        return journal
    fix.suggested, fix.decided_by = False, "user"
    _save(book_dir, journal)
    return journal
