"""Book processing by stages: one model per stage over the whole book, resumable via work/state.sqlite."""
from __future__ import annotations

import json
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from techbookocr.config import Config, ConfigError
from techbookocr.ingest.pipeline import ingest_book
from techbookocr.models.doclayout import DocLayoutDetector
from techbookocr.models.registry import make_adapter
from techbookocr.models.types import Block
from techbookocr.models.server import server_for
from techbookocr.obsidian import frontmatter, moc_name, moc_note
from techbookocr.pipeline.arbiter import fallback, run_arbiter
from techbookocr.pipeline.assemble import book_meta, render_book, write_text_atomic
from techbookocr.pipeline.consensus import run_consensus
from techbookocr.pipeline.crops import PageImages
from techbookocr.pipeline.drafts import TABLE_MODEL_KINDS, TEXT_MODEL_KINDS, run_drafts
from techbookocr.pipeline.lang import detect_lang, sample_texts
from techbookocr.pipeline.layout import run_layout
from techbookocr.pipeline.postproc.run import postprocess
from techbookocr.pipeline.postproc.spell import load_speller, speller_langs
from techbookocr.pipeline.quality import quality_stats, render_quality
from techbookocr.pipeline.sketches import run_sketches
from techbookocr.pipeline.state import PAGE_CATEGORY, STAGES, BookState, PageEntry
from techbookocr.pipeline.transport import TRANSPORT_ERRORS, StageAborted, TransportGuard

MODES = ("cascade", "fast")
LANGS = ("ru", "en", "de")


@dataclass(frozen=True)
class RunOptions:
    mode: str = "cascade"
    lang: str | None = None
    redo: str | None = None
    scans: list[int] | None = None
    give_up_transport: bool = False  # mark items left pending due to transport failures as failed
    keep_work: bool = False          # True → do not delete work/ after assembly (debugging state.sqlite, --redo)
    models: bool = False             # for born-digital PDFs: a model pass over vision pages and the table arbiter


class _Log:
    """Log work/logs/run.log and (optionally) console output."""

    def __init__(self, path: Path, echo: Callable[[str], None] | None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.echo = path, echo

    def __call__(self, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if self.echo:
            self.echo(line)


def page_entries(refs, work_dir: Path) -> list[PageEntry]:
    entries = []
    for r in refs:
        if r.file:
            with Image.open(work_dir / "pages" / r.file) as im:
                w, h = im.size
            file = f"pages/{r.file}"
        else:  # lazy-ingest (text layer): no file, sizes are virtual at r.dpi
            w, h, file = r.width, r.height, ""
        entries.append(PageEntry(name=r.name, idx=r.scan * 2 + (1 if r.side == "R" else 0), scan=r.scan,
                                 side=r.side, file=file, width=w, height=h, blank=r.blank))
    return entries


def finish_book(state: BookState, out_dir: Path, *, book_name: str, source: str, lang: str, mode: str,
                models: dict[str, str], speller, pipeline=None, images=None,
                log: Callable[[str], None] = lambda m: None) -> None:
    """Postprocessing and assembly: book.md, <book_name>.md (MOC), meta.json, quality.md.
    A pure function of state — repeated calls are safe."""
    pages = state.pages()
    if images is None:
        images = PageImages(state.path.parent, {p.name: p.file for p in pages})
    post = postprocess(pages, state.blocks(), speller, cfg=pipeline, images=images)
    state.set_printed(post.printed)
    state.mark_done("postproc")
    pages, blocks = state.pages(), state.blocks()
    md, notes = render_book(post, pages)
    stats = quality_stats(pages, blocks, post.spell)
    extraction = None
    if state.get_meta("textlayer") == "1":
        try:
            extraction = json.loads(state.get_meta("extract:stats") or "{}") or None
        except json.JSONDecodeError:
            pass
    meta = book_meta(book_name, source, pages, post.printed, lang, mode, models, stats,
                     extraction=extraction, timings=state.timings())
    moc = moc_note(book_name, meta, md)  # MOC is built from the book.md body before frontmatter is added
    write_text_atomic(out_dir / "book.md", frontmatter(meta) + md)
    write_text_atomic(out_dir / f"{moc_name(book_name)}.md", moc)
    write_text_atomic(out_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    write_text_atomic(out_dir / "quality.md",
                      render_quality(book_name, pages, blocks, stats, post.spell, notes, state.timings(),
                                     post.spans, post.suspects))
    try:  # fix journal for the Fixes screen; a failure does not break assembly, the journal is rebuilt from quality.md
        from techbookocr.fixes.review import journal_from_blocks
        journal_from_blocks(out_dir, blocks, pages, images=images, cfg=pipeline, log=log)  # + scan crops
    except Exception as e:  # noqa: BLE001
        log(f"fix journal: {type(e).__name__}: {e}")
        (out_dir / "fixes.json").unlink(missing_ok=True)  # the old journal does not match the new book.md
        shutil.rmtree(out_dir / "fixes", ignore_errors=True)  # nor do the scan crops of the previous assembly
    state.mark_done("assemble")


def validate(cfg: Config, opts: RunOptions) -> None:
    if opts.mode not in MODES:
        raise ConfigError(f"mode must be one of {MODES}, got {opts.mode!r}")
    if opts.lang is not None and opts.lang not in LANGS:
        raise ConfigError(f"lang must be one of {LANGS}, got {opts.lang!r}")
    if opts.redo is not None and opts.redo not in STAGES:
        raise ConfigError(f"redo must be one of {STAGES}, got {opts.redo!r}")
    p = cfg.pipeline
    needed = [p.layout_model, p.arbiter_model] + ([p.text_model, p.table_model] if opts.mode == "cascade" else [])
    missing = [k for k in needed if k not in cfg.models]
    if missing:
        raise ConfigError(f"models not in config: {', '.join(missing)}")


def sync_pages(state: BookState, entries: list[PageEntry], renders: dict[str, str] | None = None) -> list[str]:
    """Reconcile the pages in state with the ingest result. Pages whose size, file, idx or
    render parameters changed, as well as names that disappeared from this run's frames (split_spreads change), are deleted
    together with their blocks and added anew — the layout stage runs again for them. Returns the deleted names."""
    renders = renders or {}
    known = {pg.name: pg for pg in state.pages()}
    new_names = {e.name for e in entries}
    scans = {e.scan for e in entries}
    drop = [n for n, pg in known.items() if pg.scan in scans and n not in new_names]
    for e in entries:
        old = known.get(e.name)
        if old is None:
            continue
        stored = state.get_meta(f"render:{e.name}")
        if e.file:                      # regular entry — compare file and sizes exactly
            changed = (old.idx, old.width, old.height, old.file) != \
                      (e.idx, e.width, e.height, e.file)
        else:                           # lazy entry: the file appears on re-render for the models
            changed = (old.idx, old.width, old.height) != (e.idx, e.width, e.height)
        if changed or (stored is not None and e.name in renders and stored != renders[e.name]):
            drop.append(e.name)
    state.remove_pages(drop)
    state.add_pages(entries)
    for e in entries:
        if e.name in renders:
            state.set_meta(f"render:{e.name}", renders[e.name])
    return drop


def _mark_failed(state: BookState, stage: str, item, msg: str) -> None:
    """Mark an item failed (with the arbiter's fallback result) so that the stage can proceed."""
    if stage == "layout":
        pg = state.page(item)
        state.set_layout(item, [Block(PAGE_CATEGORY, "", (0, 0, pg.width, pg.height))], status="failed", error=msg)
    elif stage == "sketches":
        state.update_block(item, sketches_status="failed", sketches_error=msg)
    elif stage == "drafts":
        state.update_block(item, drafts_status="failed", b_error=msg)
    elif stage == "arbiter":
        b = state.block(item)
        text, src = fallback(b.text_a, b.text_b if b.drafts_status == "done" else None)
        state.update_block(item, arbiter_status="failed", arbiter_error=msg, arbiter_note="poison" if msg.startswith("poison") else "gave up",
                           final=text, final_source=src)


def _mark_poison(state: BookState, stage: str, item) -> None:
    _mark_failed(state, stage, item, f"poison: {stage} kills the server while other items succeed")


def _canary_image() -> Image.Image:
    img = Image.new("RGB", (320, 96), "white")
    ImageDraw.Draw(img).rectangle([20, 30, 300, 50], fill="black")
    return img


def _load_suspects(state: BookState, key: str) -> list[str]:
    try:
        v = json.loads(state.get_meta(key) or "[]")
    except json.JSONDecodeError:
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def _ping(call) -> bool:
    """Canary: a request on a synthetic image; the result is discarded, only connectivity matters."""
    try:
        call()
    except TRANSPORT_ERRORS:
        return False
    return True


def _guarded(g: TransportGuard, fn):
    """Run a stage; items with a transport failure stay pending → StageAborted (the book is not assembled)."""
    n = fn(g)
    g.finish()
    return n


def run_pages(entries: list[PageEntry], out_dir: Path, cfg: Config, opts: RunOptions, *, book_name: str,
              source: str, server_factory=server_for, adapter_factory=make_adapter,
              detector_factory=DocLayoutDetector, speller_factory=load_speller, sleep=time.sleep,
              echo: Callable[[str], None] | None = print,
              renders: dict[str, str] | None = None,
              control=None, textlayer: bool = False) -> Path:
    # control is a duck-typed object with poll() and set_stage(stage) (daemon commands, pipeline/control.py;
    # not imported here: control.py pulls in library.py, which runner must not know about). None — a normal run.
    validate(cfg, opts)
    if not entries:
        raise ConfigError("book has no pages")
    p = cfg.pipeline
    out_dir = Path(out_dir)
    work = out_dir / "work"
    log = _Log(work / "logs" / "run.log", echo)
    state = BookState(work / "state.sqlite")
    try:
        dropped = sync_pages(state, entries, renders)
        if dropped:
            log(f"pages re-ingested, layout will be redone: {len(dropped)}")
        state.restore_deferred()
        if opts.redo:
            state.reset_stage(opts.redo)
            log(f"redo from {opts.redo}")
        prev_mode = state.get_meta("mode")
        if prev_mode and prev_mode != opts.mode:
            state.reset_stage("drafts")
            log(f"mode {prev_mode} -> {opts.mode}: drafts and later stages reset")
        state.set_meta("mode", opts.mode)
        if opts.give_up_transport:
            for stage in ("layout", "sketches", "drafts", "arbiter"):
                for item in state.transport_pending(stage):
                    _mark_failed(state, stage, item, f"gave up: {stage} item left pending by transport errors")
                    log(f"{stage}: {item} marked failed (--give-up-transport)")
        if any(state.pending(s) for s in STAGES[:5]):
            state.reset_stage("postproc")

        def guard() -> TransportGuard:
            return TransportGuard(p.transport_retries, p.max_consecutive_failures, sleep=sleep,
                                  control=control.poll if control else None)

        def stage_attempts(stage: str, tag: str, open_resource, work_fn, ping) -> None:
            """A stage with one resource (server) restart on a series of transport failures.

            A "poisonous" item kills the server while the rest are processed. The first items of aborted series
            are remembered (meta abort:<tag>, a JSON list of suspects). On a new pass the suspects are deferred
            (in memory only), the rest are processed; then the suspects are tried one by one. If the same one
            again breaks the connection alone, and the server is known to be alive (the others completed, or if there were none, the
            canary ping request on a synthetic image passed), the item is marked failed. If the server is not alive
            (outage), nothing is marked, items stay pending, the stage is aborted."""
            if control:
                control.set_stage(stage)
            key = f"abort:{tag}"
            attempt = 1
            while True:
                t0 = time.monotonic()
                restart = False
                try:
                    with open_resource() as model:
                        suspects = [s for s in _load_suspects(state, key) if state.defer(stage, s)]
                        n = 0
                        try:
                            n = work_fn(model)
                            while suspects:
                                s = suspects[0]
                                state.undefer(stage, s)
                                alive = n >= 1 or ping(model)
                                try:
                                    n += work_fn(model)
                                except StageAborted as e2:
                                    if alive and [str(i) for i in e2.items] == [s]:
                                        _mark_poison(state, stage, s if stage == "layout" else int(s))
                                        log(f"{stage}: item {s} kills the server while others work: failed (poison)")
                                        state.set_meta(key, json.dumps([x for x in _load_suspects(state, key) if x != s]))
                                        suspects.pop(0)
                                        restart = True  # the server is "killed" — a new one is needed
                                        break
                                    raise
                                state.set_meta(key, json.dumps([x for x in _load_suspects(state, key) if x != s]))
                                suspects.pop(0)
                        finally:
                            state.clear_deferred()
                    if restart:
                        continue
                    state.set_meta(key, "[]")
                    log(f"{stage}: {tag} processed {n}")
                    return
                except StageAborted as e:
                    e.stage = stage
                    log(f"{stage}: {e} (attempt {attempt}), items stay pending")
                    known = _load_suspects(state, key)
                    first = [str(e.items[0])] if e.items else []
                    state.set_meta(key, json.dumps(known + [x for x in first if x not in known]))
                    if attempt == 2:
                        raise
                    attempt += 1
                finally:
                    state.add_seconds(stage, time.monotonic() - t0)

        def with_model(stage: str, key: str, work_fn, ping) -> None:
            spec = cfg.models[key]

            @contextmanager
            def open_model():
                with server_factory(spec, cfg.server) as server:
                    model = adapter_factory(spec, server.base_url)
                    try:
                        yield model
                    finally:
                        model.close()

            stage_attempts(stage, f"{stage}:{key}", open_model, work_fn, ping)

        if textlayer:
            state.set_meta("textlayer", "1")
        # model stages for a born-digital book — only in the --models pass
        models_on = not textlayer or opts.models

        def prep_images() -> None:
            if textlayer:
                from techbookocr.pipeline.textlayer import render_pending_pages
                render_pending_pages(state, Path(source), work, log)

        if textlayer and state.pending("layout"):
            from techbookocr.pipeline.textlayer import run_extract
            log(f"extract: {run_extract(state, Path(source), work, out_dir, p, log)} pages from text layer")
        if state.pending("layout") and models_on:
            prep_images()
            with_model("layout", p.layout_model,
                       lambda m: _guarded(guard(), lambda g: run_layout(state, m, work, out_dir,
                                       p.figure_pad, g, log, webp_quality=p.webp_quality)),
                       lambda m: _ping(lambda: m.ocr_page(_canary_image())))
        if opts.mode == "fast":
            state.skip_pending("drafts")  # blocks appear after layout
        prev_lang = state.get_meta("lang")
        lang = opts.lang or prev_lang or detect_lang(
            sample_texts(state.pages(), state.blocks(), p.lang_sample_pages))
        if prev_lang and prev_lang != lang:
            state.reset_stage("arbiter")  # the language goes into the arbiter prompt
            log(f"lang {prev_lang} -> {lang}: arbiter and later stages reset")
        state.set_meta("lang", lang)

        if state.pending("sketches") and models_on:
            prep_images()

            @contextmanager
            def open_detector():
                det = detector_factory(stderr_path=work / "logs" / "doclayout.log",
                                       threshold=min(0.2, p.sketch_threshold),
                                       device=p.sketches_device)
                try:
                    yield det
                finally:
                    det.close()

            stage_attempts("sketches", "sketches", open_detector,
                           lambda d: _guarded(guard(), lambda g: run_sketches(state, d, work, out_dir, p, g, log)),
                           lambda d: _ping(lambda: d.detect(_canary_image())))

        if opts.mode == "cascade" and models_on:
            if state.pending("drafts", TEXT_MODEL_KINDS):
                prep_images()
                with_model("drafts", p.text_model,
                           lambda m: _guarded(guard(), lambda g: run_drafts(state, m, work, p, g, TEXT_MODEL_KINDS, log)),
                           lambda m: _ping(lambda: m.ocr_block(_canary_image(), "text")))
            if state.pending("drafts", TABLE_MODEL_KINDS):
                prep_images()
                with_model("drafts", p.table_model,
                           lambda m: _guarded(guard(), lambda g: run_drafts(state, m, work, p, g, TABLE_MODEL_KINDS, log)),
                           lambda m: _ping(lambda: m.ocr_block(_canary_image(), "table")))

        if state.pending("consensus"):
            if control:
                control.set_stage("consensus")
            log(f"consensus: {run_consensus(state, p.tau_text, opts.mode)}")
        if state.pending("arbiter") and models_on:
            prep_images()
            # dictionary for the "replaces dictionary word" rule in sanitize_fixes (reverting arbiter fixes)
            fix_speller = (speller_factory(speller_langs(lang), Path(p.dict_dir).expanduser(), log)
                           if p.fix_reject_dictionary_words else None)
            # pairs the user reverted on the Fixes screen (out/rejected-fixes.json in the library root)
            from techbookocr.fixes.rejected import denied_pairs
            denied = denied_pairs(Path(cfg.library.dir), log)
            with_model("arbiter", p.arbiter_model,
                       lambda m: _guarded(guard(), lambda g: run_arbiter(state, m, work, p, lang, g, log,
                                                                         speller=fix_speller, denied=denied)),
                       lambda m: _ping(lambda: m.ask(_canary_image(), "Reply with the single word OK.", max_tokens=16)))

        if state.pending("postproc") or state.pending("assemble"):
            if control:
                control.set_stage("postproc")
            t0 = time.monotonic()
            speller = speller_factory(speller_langs(lang), Path(p.dict_dir).expanduser(), log)
            models = {"layout": p.layout_model, "arbiter": p.arbiter_model}
            if opts.mode == "cascade":
                models |= {"text": p.text_model, "table": p.table_model}
            images = None
            if textlayer:
                from techbookocr.pipeline.crops import PdfPageImages
                images = PdfPageImages(work, {pg.name: pg.file for pg in state.pages()},
                                       Path(source), state.pages())
            finish_book(state, out_dir, book_name=book_name, source=source, lang=lang, mode=opts.mode,
                        models=models, speller=speller, pipeline=p, images=images, log=log)
            state.add_seconds("assemble", time.monotonic() - t0)
            if textlayer:
                pend_pages = state.pending("layout")
                pend_tables = sum(b.origin == "layer" and b.category == "Table"
                                  and b.arbiter_status == "pending" for b in state.blocks())
                if pend_pages or pend_tables:
                    log(f"awaiting --models: {pend_pages} pages for OCR, "
                        f"{pend_tables} tables for arbiter")
            log(f"done: {out_dir / 'book.md'}")
    finally:
        state.close()
    return out_dir


def run_book(book: Path, out_root: Path, cfg: Config, opts: RunOptions, **deps) -> Path:
    """Book → out_root/<stem>/: ingest (resumable) and all stages."""
    validate(cfg, opts)  # before ingest: a configuration error must not cost hours of rendering
    book = Path(book)
    out_dir = Path(out_root) / book.stem
    work = out_dir / "work"
    BookState(work / "state.sqlite").close()  # the state schema is checked before rendering
    lazy = False
    if book.suffix.lower() == ".pdf" and cfg.pipeline.text_layer != "off":
        import pymupdf
        from techbookocr.pipeline.textlayer import probe_pdf
        doc = pymupdf.open(str(book))
        lazy = cfg.pipeline.text_layer == "force" or \
            probe_pdf(doc, cfg.pipeline.textlayer_probe_pages)
        doc.close()
    refs = ingest_book(book, work, cfg.render, opts.scans, lazy=lazy)
    renders = {r.name: json.dumps(r.render, sort_keys=True) for r in refs if r.render is not None}
    out = run_pages(page_entries(refs, work), out_dir, cfg, opts, book_name=book.stem, source=str(book),
                    renders=renders, textlayer=lazy, **deps)
    if not opts.keep_work:
        shutil.rmtree(work, ignore_errors=True)  # the book is assembled: renders and state are no longer needed
    return out
