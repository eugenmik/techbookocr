"""CLI techbookocr."""
import os
import shlex
import shutil
import sys
from pathlib import Path

import typer

from techbookocr.config import load_config

app = typer.Typer(no_args_is_help=True, help="Local OCR of technical books to Markdown")


@app.callback()
def main() -> None:
    """techbookocr."""


def _parse_scans(scans: str | None) -> list[int] | None:
    """«0,5,10-12» → [0, 5, 10, 11, 12]."""
    if not scans:
        return None
    out: list[int] = []
    for part in scans.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                raise typer.BadParameter(f"bad --scans part {part!r}") from None
            if lo > hi:
                raise typer.BadParameter(f"reversed range {part!r} in --scans (use {b}-{a})")
            out += range(lo, hi + 1)
        else:
            try:
                out.append(int(part))
            except ValueError:
                raise typer.BadParameter(f"bad --scans part {part!r}") from None
    return out


@app.command()
def ingest(
    book: Path,
    work: Path = typer.Option(..., help="Book work directory"),
    scans: str = typer.Option(None, help="Scan numbers, comma-separated (all by default)"),
    config: Path = typer.Option(None, help="Path to techbookocr.toml"),
) -> None:
    """Render a book into work/pages/*.png."""
    from techbookocr.ingest.pipeline import ingest_book

    refs = ingest_book(book, work, load_config(config).render, _parse_scans(scans))
    typer.echo(f"{len(refs)} pages → {work / 'pages'}")


@app.command("try-model")
def try_model(key: str, image: Path, config: Path = typer.Option(None)) -> None:
    """Start model KEY, OCR one image, print Markdown (adapter debugging)."""
    from PIL import Image

    from techbookocr.models.registry import make_adapter
    from techbookocr.models.server import server_for

    cfg = load_config(config)
    if key not in cfg.models:
        typer.echo(f"Unknown model {key!r}. Available: {', '.join(cfg.models)}", err=True)
        raise typer.Exit(2)
    spec = cfg.models[key]
    with server_for(spec, cfg.server) as server:
        ocr = make_adapter(spec, server.base_url)
        try:
            res = ocr.ocr_page(Image.open(image).convert("RGB"))
        finally:
            ocr.close()
    typer.echo(res.markdown)
    typer.echo(f"--- {res.seconds:.1f}s, blocks={len(res.blocks)}, error={res.error}", err=True)


GOLDEN_DIR = Path("eval/golden")


@app.command("golden-candidates")
def golden_candidates(
    books_dir: Path = typer.Argument(Path("test_books")),
    out: Path = typer.Option(Path("eval/candidates")),
    every: int = typer.Option(15, min=1, help="Every Nth scan"),
    config: Path = typer.Option(None),
) -> None:
    """Render candidate scans for picking golden pages (downscaled copies for review)."""
    from techbookocr.eval.golden import candidate_name
    from techbookocr.ingest.source import open_book

    out.mkdir(parents=True, exist_ok=True)
    cfg = load_config(config).render
    count = 0
    for book in sorted(books_dir.iterdir()):
        if book.suffix.lower() not in (".djvu", ".pdf"):
            continue
        with open_book(book) as src:
            for scan in range(0, src.page_count, every):
                img, _ = src.render(scan, max_dpi=cfg.max_dpi, min_dpi=cfg.min_dpi)
                img.thumbnail((1400, 1400))
                img.save(out / candidate_name(book, scan), quality=80)
                count += 1
    typer.echo(f"{count} candidates → {out}")


@app.command("golden-extract")
def golden_extract(books_dir: Path = typer.Argument(Path("test_books")), config: Path = typer.Option(None)) -> None:
    """Extract golden pages from the manifest into eval/golden/<id>.png."""
    from techbookocr.eval.golden import extract_golden

    try:
        files = extract_golden(GOLDEN_DIR / "manifest.toml", books_dir, GOLDEN_DIR, load_config(config).render)
        typer.echo(f"{len(files)} golden pages")
    except (FileNotFoundError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)


@app.command("golden-review")
def golden_review() -> None:
    """Generate eval/golden/review.html for a visual check of the golden set."""
    from techbookocr.eval.golden import write_review_html

    typer.echo(str(write_review_html(GOLDEN_DIR)))


RUNS_DIR = Path("eval/runs")


@app.command("eval")
def eval_cmd(models: str = typer.Option(None, help="Model keys, comma-separated (all by default)"),
             config: Path = typer.Option(None)) -> None:
    """Run candidate models on the golden set (cached) and write eval/report.md."""
    from techbookocr.eval.report import build_report
    from techbookocr.eval.runner import run_candidates

    cfg = load_config(config)
    keys = [k.strip() for k in models.split(",")] if models else list(cfg.models)
    unknown = [k for k in keys if k not in cfg.models]
    if unknown:
        typer.echo(f"Unknown model(s): {', '.join(unknown)}. Available: {', '.join(cfg.models)}", err=True)
        raise typer.Exit(2)
    failed = run_candidates(cfg, keys, GOLDEN_DIR, RUNS_DIR)
    Path("eval/report.md").write_text(build_report(GOLDEN_DIR, RUNS_DIR), encoding="utf-8")
    typer.echo("eval/report.md")
    if failed:
        typer.echo(f"Failed models: {', '.join(failed)}", err=True)
        raise typer.Exit(1)


@app.command("eval-report")
def eval_report() -> None:
    """Rebuild eval/report.md from existing runs."""
    from techbookocr.eval.report import build_report

    Path("eval/report.md").write_text(build_report(GOLDEN_DIR, RUNS_DIR), encoding="utf-8")
    typer.echo("eval/report.md")


@app.command("run")
def run_cmd(
    book: Path,
    mode: str = typer.Option(None, help="cascade | fast (default — mode from [pipeline])"),
    lang: str = typer.Option(None, help="ru | en | de (default — detected from first pages)"),
    redo: str = typer.Option(None, help="Recompute a stage and all later ones: layout, sketches, drafts, "
                                        "consensus, arbiter, postproc, assemble"),
    scans: str = typer.Option(None, help="Scans: 0,5,10-20 (all by default)"),
    out: Path = typer.Option(Path("out"), help="Output directory"),
    config: Path = typer.Option(None, help="Path to techbookocr.toml"),
    give_up_transport: bool = typer.Option(False, "--give-up-transport", help="Give up on transport failures: mark elements left unprocessed by server outages as failed and assemble the book with what exists. Without it such a book is not assembled — re-run later"),
    keep_work: bool = typer.Option(False, "--keep-work", help="Keep the work/ directory (page renders, state.sqlite) after the book is assembled — needed for --redo and debugging"),
    models: bool = typer.Option(False, "--models", help="For born-digital PDF (text layer): model pass — OCR pages without a layer and arbitrate flagged tables. Without it the fast text-only pass assembles the book and leaves them pending"),
) -> None:
    """Process one book (cascade or fast mode); re-running resumes from the checkpoint."""
    import signal
    import traceback

    from techbookocr.config import ConfigError
    from techbookocr.models.server import ServerError
    from techbookocr.pipeline.runner import LANGS, MODES, RunOptions, run_book
    from techbookocr.pipeline.state import STAGES
    from techbookocr.pipeline.transport import StageAborted

    if not book.exists():
        typer.echo(f"Book not found: {book}", err=True)
        raise typer.Exit(2)
    if (mode is not None and mode not in MODES) or (lang is not None and lang not in LANGS) \
            or (redo is not None and redo not in STAGES):
        typer.echo(f"Invalid option: mode in {MODES}, lang in {LANGS}, redo in {STAGES}", err=True)
        raise typer.Exit(2)
    scan_list = _parse_scans(scans)
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)
    mode = mode or cfg.pipeline.mode  # without --mode, mode comes from [pipeline]

    def _terminate(signum, frame):  # SIGTERM -> KeyboardInterrupt: contexts close, containers stop
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate)
    try:
        out_dir = run_book(book, out, cfg, RunOptions(mode=mode, lang=lang, redo=redo, scans=scan_list,
                                                          give_up_transport=give_up_transport,
                                                          keep_work=keep_work, models=models))
    except StageAborted as e:
        stage = f" at stage {e.stage}" if e.stage else ""
        typer.echo(f"Aborted{stage}: {e}. Re-run `techbookocr run` without --redo — processing resumes "
                   f"from the checkpoint.", err=True)
        raise typer.Exit(1)
    except ServerError as e:
        typer.echo(f"Aborted: {e}. Re-run `techbookocr run` without --redo — processing resumes "
                   f"from the checkpoint.", err=True)
        raise typer.Exit(1)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)
    except Exception:
        log = out / book.stem / "work" / "logs" / "run.log"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except OSError:
            pass
        raise
    typer.echo(str(out_dir / "book.md"))


CASCADE_DIR = Path("eval/cascade")


@app.command("eval-cascade")
def eval_cascade(
    arbiter: str = typer.Option(..., help="Arbiter model key from techbookocr.toml"),
    mode: str = typer.Option("cascade", help="cascade | fast"),
    sweep: bool = typer.Option(False, help="Send every mismatching block to the arbiter — for threshold tuning"),
    seed: str = typer.Option(None, help="eval/cascade/ variant whose layout and drafts are reused"),
    config: Path = typer.Option(None),
) -> None:
    """Run the golden set through the cascade: eval/cascade/<mode>-<arbiter>/book.md."""
    from techbookocr.eval.cascade import run_golden
    from techbookocr.pipeline.runner import MODES

    cfg = load_config(config)
    if arbiter not in cfg.models or mode not in MODES:
        typer.echo(f"Unknown arbiter {arbiter!r} or mode {mode!r}. Models: {', '.join(cfg.models)}", err=True)
        raise typer.Exit(2)
    if seed is not None and not (CASCADE_DIR / seed / "work" / "state.sqlite").exists():
        typer.echo(f"Seed variant not found: {CASCADE_DIR / seed}", err=True)
        raise typer.Exit(2)
    out = run_golden(cfg, GOLDEN_DIR, CASCADE_DIR / f"{mode}-{arbiter}", arbiter=arbiter, mode=mode, sweep=sweep,
                     seed=CASCADE_DIR / seed if seed else None)
    typer.echo(str(out / "book.md"))


@app.command("eval-cascade-report")
def eval_cascade_report(
    tau_text: str = typer.Option("0,0.005,0.01,0.02,0.05", help="tau_text grid"),
    tau_halluc: str = typer.Option("0.1,0.15,0.25", help="tau_halluc grid"),
    halluc_abs_chars: str = typer.Option("1,3,5", help="halluc_abs_chars grid (allowed edit, in chars)"),
    config: Path = typer.Option(None),
) -> None:
    """Compare cascade variants with single models and sweep thresholds: eval/cascade-report.md."""
    from techbookocr.eval.cascade import cascade_report
    from techbookocr.pipeline.postproc.spell import load_speller, speller_langs

    p = load_config(config).pipeline
    speller = load_speller(speller_langs("ru"), Path(p.dict_dir).expanduser())
    text = cascade_report(GOLDEN_DIR, RUNS_DIR, CASCADE_DIR, p.tau_text, p.tau_halluc,
                          [float(x) for x in tau_text.split(",")], [float(x) for x in tau_halluc.split(",")],
                          [int(x) for x in halluc_abs_chars.split(",")], speller, p.halluc_abs_chars)
    Path("eval/cascade-report.md").write_text(text, encoding="utf-8")
    typer.echo("eval/cascade-report.md")


# --- library queue ---


def _load_cfg(config: Path | None):
    """load_config with a run_cmd-style error: ConfigError -> Exit(2)."""
    from techbookocr.config import ConfigError

    try:
        return load_config(config)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)


def _open_library(out: Path | None, config: Path | None):
    """Library at the --out root, otherwise [library] dir from the config."""
    from techbookocr.config import ConfigError
    from techbookocr.library import Library

    try:
        root = Path(out) if out is not None else Path(load_config(config).library.dir)
        return Library(root)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)


@app.command()
def add(
    paths: list[Path] = typer.Argument(..., help=".djvu/.pdf files and/or directories with them (recursive)"),
    out: Path = typer.Option(None, help="Library root (default — [library] dir from config)"),
    config: Path = typer.Option(None, help="Path to techbookocr.toml"),
) -> None:
    """Add books to the library queue."""
    from techbookocr.ingest.source import scan_count
    from techbookocr.library import expand_inputs

    files, skipped = expand_inputs(paths)  # before opening the library: its own library.sqlite does not count as input
    with _open_library(out, config) as lib:
        res = lib.add(files)
        by_name = {f.stem: f for f in files}
        for name in res.added:
            lib.set_scans(name, scan_count(by_name[name]))  # for the panel's forecast
    for name in res.added:
        typer.echo(f"added: {name}")
    for path, reason in [(str(p), r) for p, r in skipped] + res.skipped:
        typer.echo(f"skipped: {path} — {reason}")
    typer.echo(f"added {len(res.added)}, skipped {len(skipped) + len(res.skipped)}")


@app.command()
def daemon(
    out: Path = typer.Option(None, help="Library root (default — [library] dir from config)"),
    config: Path = typer.Option(None, help="Path to techbookocr.toml"),
) -> None:
    """Queue daemon: processes queued books one by one until stop or Ctrl+C."""
    import signal

    from techbookocr.config import ConfigError
    from techbookocr.daemon import DaemonLock, run_daemon
    from techbookocr.pipeline.runner import RunOptions

    cfg = _load_cfg(config)

    def _terminate(signum, frame):  # SIGTERM -> KeyboardInterrupt: the lock is released, the book stays resumable
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate)
    with _open_library(out, config) as lib:
        try:
            with DaemonLock(lib.root):  # daemon.lock lives at the library root
                run_daemon(lib, cfg, RunOptions(mode=cfg.pipeline.mode), out_root=lib.root,
                           echo=typer.echo)
        except ConfigError as e:  # "daemon already running"
            typer.echo(str(e), err=True)
            raise typer.Exit(1)
        except KeyboardInterrupt:
            typer.echo("daemon stopped")
            raise typer.Exit(0)


@app.command()
def status(
    out: Path = typer.Option(None, help="Library root (default — [library] dir from config)"),
    config: Path = typer.Option(None, help="Path to techbookocr.toml"),
) -> None:
    """Daemon state, book counts by status, and the last 10 events."""
    from techbookocr.library import BOOK_STATUSES

    with _open_library(out, config) as lib:
        alive = lib.daemon_alive()
        state = lib.get_meta("daemon_state") or "never ran"
        typer.echo(f"daemon: {'alive' if alive else 'dead'} ({state})")
        counts = {s: 0 for s in BOOK_STATUSES}
        for b in lib.books():
            counts[b.status] = counts.get(b.status, 0) + 1  # a manual status edit must not break status
            if b.status == "processing":
                typer.echo(f"processing book: {b.name} ({b.stage})")
        for s in BOOK_STATUSES:
            typer.echo(f"{s}: {counts[s]}")
        typer.echo("events:")
        for e in reversed(lib.events(10)):
            typer.echo(f"{e.ts} {e.book or '-'} {e.level} {e.message}")


@app.command()
def bridge(
    out: Path = typer.Option(None, help="Library root (default — [library] dir from config)"),
    config: Path = typer.Option(None, help="Path to techbookocr.toml"),
) -> None:
    """JSON-lines bridge for the techbookocr-tui panel (protocol v1). Not for interactive use."""
    from techbookocr.tui.bridge import serve_stdio

    import json

    from techbookocr.config import ConfigError

    try:
        root = Path(out) if out is not None else Path(load_config(config).library.dir).expanduser()
    except ConfigError as e:  # the panel reads the first stdout line: answer with the protocol
        typer.echo(json.dumps({"ready": False, "v": 1, "error": f"ConfigError: {e}"}, ensure_ascii=False))
        raise typer.Exit(2)
    raise typer.Exit(serve_stdio(root, config))


def _push_if_alive(command: str, out: Path | None, config: Path | None) -> None:
    """A command is written for the daemon only while it is alive: after startup it would be stale and eaten in vain."""
    with _open_library(out, config) as lib:
        if not lib.daemon_alive():
            typer.echo("daemon is not running — command not written", err=True)
            raise typer.Exit(1)
        lib.push_command(command)
    typer.echo(f"command {command} written")


@app.command()
def pause(out: Path = typer.Option(None), config: Path = typer.Option(None)) -> None:
    """Pause the daemon (between model requests); the book resumes on resume."""
    _push_if_alive("pause", out, config)


@app.command()
def resume(out: Path = typer.Option(None), config: Path = typer.Option(None)) -> None:
    """Resume a paused daemon."""
    _push_if_alive("resume", out, config)


@app.command()
def stop(out: Path = typer.Option(None), config: Path = typer.Option(None)) -> None:
    """Stop the daemon; the in-flight book returns to the queue resumable."""
    _push_if_alive("stop", out, config)


def _book_command(command: str, name: str, arg: str | None, out: Path | None, config: Path | None) -> None:
    """Daemon alive: the command goes to the queue; dead: apply immediately (the book is not in work, the action is instant)."""
    from datetime import datetime

    from techbookocr.library import Command
    from techbookocr.pipeline.control import apply_command

    with _open_library(out, config) as lib:
        if lib.daemon_alive():
            lib.push_command(command, book=name, arg=arg)
        else:
            cmd = Command(id=-1, command=command, book=name, arg=arg,
                          created_at=datetime.now().isoformat(timespec="seconds"))
            try:
                apply_command(lib, cmd, None)
            except KeyError:
                typer.echo(f"book not found: {name}", err=True)
                raise typer.Exit(2)
            # A refusal from apply_command goes only to events: check the outcome so we do not reply with success
            want = {"skip": "skipped", "retry": "queued"}.get(command)
            if want is not None and lib.book(name).status != want:
                typer.echo(f"{command} {name} rejected: book is {lib.book(name).status}", err=True)
                raise typer.Exit(1)
    typer.echo(f"{command} {name}" + (f" {arg}" if arg is not None else ""))


@app.command()
def skip(name: str, out: Path = typer.Option(None), config: Path = typer.Option(None)) -> None:
    """Skip a book: queued → skipped (in-flight — interrupts it)."""
    _book_command("skip", name, None, out, config)


@app.command()
def retry(name: str, out: Path = typer.Option(None), config: Path = typer.Option(None)) -> None:
    """Return a book to the queue: failed/skipped → queued."""
    _book_command("retry", name, None, out, config)


@app.command()
def priority(name: str, n: int, out: Path = typer.Option(None), config: Path = typer.Option(None)) -> None:
    """Book priority: higher runs earlier in the queue."""
    _book_command("priority", name, str(n), out, config)


@app.command()
def summarize(
    name: str = typer.Argument(None, help="Book name (directory under the library root)"),
    all_books: bool = typer.Option(False, "--all", help="All assembled books missing a summary"),
    redo: bool = typer.Option(False, "--redo", help="Rewrite an existing summary"),
    out: Path = typer.Option(None, help="Library root (default — [library] dir from config)"),
    config: Path = typer.Option(None, help="Path to techbookocr.toml"),
) -> None:
    """Model-generated book summary: description+keywords → MOC/meta.json and books-index.md."""
    from techbookocr import summarize as smz

    cfg = _load_cfg(config)
    root = Path(out) if out is not None else Path(cfg.library.dir)
    if not name and not all_books:
        typer.echo("give a book name or --all", err=True)
        raise typer.Exit(2)
    targets = [d.name for d in smz.book_dirs(root)] if all_books else [name]
    failed = 0
    for n in targets:
        try:
            s = smz.run_summarize(root, n, cfg, redo=redo)
        except Exception as e:
            failed += 1
            typer.echo(f"{n}: {e}", err=True)
            continue
        typer.echo(f"{n}: {'summary exists, skipped' if s is None else 'summary written'}")
    if all_books:
        smz.update_books_index(root)
    if failed:
        raise typer.Exit(1)


_FIX_ICON = {"applied": "✓", "reverted": "↶", "not_found": "·"}


@app.command()
def fixes(
    name: str = typer.Argument(..., help="Book name (directory under the library root) or path to it"),
    revert: str = typer.Option(None, "--revert", help="Fix id: restore the printed text"),
    apply: str = typer.Option(None, "--apply", help="Fix id: apply the arbiter's fix"),
    keep: str = typer.Option(None, "--keep", help="Fix id: keep as is, clear the rule suggestion"),
    out: Path = typer.Option(None, help="Library root (default — [library] dir from config)"),
    config: Path = typer.Option(None, help="Path to techbookocr.toml"),
) -> None:
    """Misprint fixes of an assembled book: list, revert to the printed text, apply, keep."""
    from techbookocr.fixes.review import FixError, check_editable, keep_fix, load_journal, peek_journal, set_fix
    from techbookocr.pipeline.postproc.spell import load_speller

    given = [(flag, v) for flag, v in (("--revert", revert), ("--apply", apply), ("--keep", keep)) if v is not None]
    if len(given) > 1:
        typer.echo(f"{', '.join(f for f, _ in given)}: only one action at a time", err=True)
        raise typer.Exit(2)
    if given and not given[0][1]:
        typer.echo(f"{given[0][0]}: empty fix id", err=True)
        raise typer.Exit(2)
    cfg = _load_cfg(config)
    root = Path(out) if out is not None else Path(cfg.library.dir)
    book_dir = Path(name) if Path(name).is_dir() else root / name
    if not (book_dir / "book.md").exists():
        typer.echo(f"no assembled book: {book_dir}", err=True)
        raise typer.Exit(2)
    lib_root = book_dir.parent
    p = cfg.pipeline
    factory = (lambda langs: load_speller(langs, Path(p.dict_dir).expanduser())) \
        if p.fix_reject_dictionary_words else None
    opts = {"library_root": lib_root, "speller_factory": factory, "dict_min_len": p.fix_dictionary_min_len}
    try:
        if revert is not None or apply is not None:
            journal = set_fix(book_dir, apply if apply is not None else revert, apply is not None, **opts)
        elif keep is not None:
            journal = keep_fix(book_dir, keep, **opts)
        elif (why := check_editable(book_dir, lib_root)):
            # book in progress: read-only, no files are written
            typer.echo(f"read-only: {why}", err=True)
            journal = peek_journal(book_dir)
        else:
            journal = load_journal(book_dir, **opts)
    except (FixError, KeyError) as e:
        typer.echo(f"{name}: {e}", err=True)
        raise typer.Exit(1)
    for f in journal.fixes:
        icon = "?" if f.suggested else _FIX_ICON[f.state]
        ref = f"{f.scan} p.{f.page}" if f.page else f.scan
        typer.echo(f"{f.id:10} {icon} {ref:14} {f.was} → {f.now}  {f.reason or ''}".rstrip())


def find_panel(env: dict, which=shutil.which, repo: Path | None = None) -> Path | None:
    """Panel binary: $TECHBOOKOCR_TUI -> the repo's panel/dist/techbookocr-tui -> techbookocr-tui on PATH."""
    if env.get("TECHBOOKOCR_TUI"):
        p = Path(env["TECHBOOKOCR_TUI"])
        return p if p.is_file() and os.access(p, os.X_OK) else None
    repo = repo if repo is not None else Path(__file__).resolve().parents[2]
    built = repo / "panel" / "dist" / "techbookocr-tui"
    if built.is_file():
        return built
    found = which("techbookocr-tui")
    return Path(found) if found else None


@app.command()
def tui(out: Path = typer.Option(None), config: Path = typer.Option(None)) -> None:
    """Library control panel (techbookocr-tui, OpenTUI). Does not stop the daemon on exit."""
    panel = find_panel(dict(os.environ))
    if panel is None and os.environ.get("TECHBOOKOCR_TUI"):
        typer.echo(f"TECHBOOKOCR_TUI={os.environ['TECHBOOKOCR_TUI']} is not an executable file", err=True)
        raise typer.Exit(2)
    if panel is None:
        typer.echo("techbookocr-tui not found. Build it: cd panel && bun install && bun run build "
                   "(or set TECHBOOKOCR_TUI to the binary)", err=True)
        raise typer.Exit(2)
    argv = [str(panel), "--bridge-cmd", shlex.join([sys.executable, "-m", "techbookocr"])]
    if out is not None:
        argv += ["--out", str(out)]
    if config is not None:
        argv += ["--config", str(Path(config).resolve())]
    try:
        os.execv(str(panel), argv)
    except OSError as e:
        typer.echo(f"cannot start {panel}: {e}", err=True)
        raise typer.Exit(2)
