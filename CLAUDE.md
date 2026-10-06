# techbookocr

Local recognition of scanned technical books (metallurgy, foundry) into Markdown, preserving tables, formulas and figures. Everything runs on this machine, no cloud.

- Input: `.djvu` or `.pdf` in `test_books/`, mostly Russian, some English and German.
- Output: `out/<book>/book.md` with YAML frontmatter, a MOC table of contents `<Name>.md`, plus `images/`, `meta.json`, `quality.md`. The working state `work/` is deleted after a successful assembly (`run --keep-work` keeps it for `--redo`/debugging).
- Result format: HTML tables with `rowspan`/`colspan`, formulas in LaTeX, figures cropped to WebP (`[pipeline] webp_quality`, default 70) and inserted as `<img>` (including inside table cells), footnotes `[^n]`, page anchors `<!-- page: 39 scan: 0018R -->`.
- Purpose: reading and RAG at the same time. A library of 100-500 books.
- Hardware: RTX 3060 12 GB. **Only one model fits in VRAM at a time.**

## Commands

```bash
uv run pytest -q                      # all tests; gpu and books markers are skipped without a GPU/books
uv run techbookocr run "test_books/<book>.djvu"          # process a book (mode from [pipeline])
uv run techbookocr run "..." --scans 0-39 --out out/trial # a range of scans into a separate folder
uv run techbookocr run "..." --models                     # born-digital PDF: finish the model pass
uv run techbookocr run "..." --redo arbiter               # recompute a stage and all following ones
uv run techbookocr add <files|folder>                     # queue books into the library
uv run techbookocr daemon                                 # process the queue, one book at a time
uv run techbookocr status                                 # daemon, counts by status, latest events
uv run techbookocr pause|resume|stop                      # commands to a running daemon
uv run techbookocr skip|retry <book>                      # skip / return to the queue
uv run techbookocr priority <book> <n>                    # priority: higher goes earlier in the queue
uv run techbookocr tui                                    # techbookocr-tui panel (OpenTUI); build: cd panel && bun install && bun run build
uv run techbookocr summarize <book> | --all              # AI summary -> description/keywords in the MOC + books-index.md
uv run --with markdown python eval/md2html.py out/*/book  # book.md -> book.html for viewing
```

Re-running `run` always resumes where it stopped: the book state lives in `work/state.sqlite`. Interrupting with Ctrl+C is safe, the model container is stopped.

## Architecture

Stages run over the whole book, one after another, each with its own model: `layout -> sketches -> drafts -> consensus -> arbiter -> postproc -> assemble`.

- **layout**: dots.mocr: blocks with boxes, categories and reading order, plus draft A of each block's text.
- **sketches**: PP-DocLayoutV3: figures inside tables. The device is `[pipeline] sketches_device` (`cpu` | `gpu`; GPU is several times faster, the stage runs while the OCR models are unloaded, so there is no VRAM conflict).
- **drafts**: draft B on block crops: HunyuanOCR for text, Chandra 2 for tables. **The stage is skipped in fast mode.**
- **consensus**: compares A and B; if they match, A is taken; if they differ, the block goes to the arbiter.
- **arbiter**: Qwen3.5-9B (llama.cpp, GGUF): looks at the crop and picks the correct variant.
- **postproc**: running headers/footers, hyphenation, paragraph stitching across pages, table continuations, footnotes, dictionary statistics.
- **assemble**: `book.md` (with frontmatter), `<Name>.md` (MOC table of contents), `meta.json`, `quality.md`.

Library flow: `techbookocr add` -> `library.sqlite` (queue) -> `techbookocr daemon` (one book at a time through the same `run_book`, resumable) -> `techbookocr tui` -> the binary `panel/dist/techbookocr-tui` (Bun + OpenTUI); data and commands go through `techbookocr bridge` (JSON lines, protocol v1, `tui/bridge.py`). The panel reads statuses and writes commands; it works with a dead daemon, and quitting with `q` does not stop the daemon.

Code: `src/techbookocr/` has `ingest/` (djvu rendering via ctypes and libdjvulibre, pdf via PyMuPDF), `models/` (adapters and docker container launch), `pipeline/` (stages, state, assembly, `control.py` for daemon commands between model requests), `library.py` (book queue in `library.sqlite`), `daemon.py` (queue loop, lock, heartbeat), `tui/` (Python side of the panel: `bridge.py` bridge, `actions.py` actions, `snapshot.py` snapshots, `data.py` read-only probes of `state.sqlite`, `settings_io.py` toml editing; the panel itself is in `panel/`, OpenTUI), `obsidian.py` (frontmatter and MOC table of contents), `eval/` (metrics and reports).

**Modes.** `fast`: dots plus the arbiter on tables and "whole page" blocks (layout failure); text and formulas come from draft A. `cascade`: full, with draft B. The default is `fast`, set in `techbookocr.toml`, key `[pipeline] mode`. The decision was based on the cascade evaluation: same quality, 2.5 times faster (see `eval/cascade-report.md`).

**PDF text layer.** `[pipeline] text_layer = auto|force|off` (default `auto`): a born-digital PDF (a text layer on at least 70% of probe pages, not multi-column) is processed without rendering and without models. `run_extract` takes text, tables (`find_tables` plus a ruling-line fallback) and figures straight from the layer, and postproc and assembly run as usual. Pages without a layer and doubtful tables stay pending; `run --models` renders only those and runs the usual stages. Statistics are in `quality.md`, section "Text-layer extraction", and in `meta.json.extraction`.

## Conventions

- **Test-driven development.** First a failing test on a minimal example from a real book, then the fix. Each fix is a separate commit.
- **Thresholds and rules are not hard-coded**; they belong in `[pipeline]` in `techbookocr.toml`.
- **Model errors are separated.** An adapter raises `TransportError` only on a connection or access failure; content errors are returned as `"truncated"`, `"looping"`, `"parse_error"`, `"bad_request: ..."`. A connection failure does **not** mark the block as failed: the block stays in the queue, the stage aborts, and the book is not assembled half-done. The `--give-up-transport` flag is an emergency exit.
- **A book must not fail as a whole** because of one block: a failed block falls back to the best draft and is listed in `quality.md`.
- **Text is never lost.** If something could not be placed (for example a sketch in a cell), it is output nearby and noted in `quality.md`.
- **Quality over speed**, but a library run takes weeks, so hangs and silent data loss are unacceptable.
- **Book misprints are corrected** (broken glyphs, obvious errors), and each one is recorded in `quality.md` as "was -> became". Typography (a hyphen instead of a dash) is not a misprint. Arbiter edits pass a deterministic check (`sanitize_fixes` in `pipeline/arbiter.py`): edits of digits and values, doubled operators, text deletion, table value shifts and replacing a term with an ordinary word are rejected and reverted to the printed form, and the report marks them `reverted: <reason>`.

## Gotchas

- **One model on the GPU at a time.** Do not run `techbookocr run` and `eval` simultaneously: starting the next model stops the other's container.
- **`pkill -f` by name also kills your own shell.** Kill by PID or use the `[b]ookocr` trick.
- **Long runs are sensitive to memory.** A run was once killed by running out of RAM because of unrelated tasks; it then resumes from where it stopped, but background waiters die silently.
- **Hugging Face downloads** need `HF_HUB_DISABLE_XET=1`, otherwise they break.

## Copying into Obsidian

`out/<book>/` is a self-contained piece of a vault. Copy: `book.md` (with frontmatter), `<Name>.md` (MOC table of contents; if the book name is `book`/`quality`, it is `<Name>-contents.md`), `images/`, the root `books-index.md`; optionally `quality.md`. Do not copy: `work/`, `meta.json`, and at the library root `library.sqlite`, `daemon.lock`, `daemon.log`. Summaries (`description`/`keywords` in the MOC) are generated by `techbookocr summarize` or the daemon (`auto_summarize`).

## Project state (October 2026)

- Foundation and model selection: done.
- Cascade (`consensus` + `arbiter`): done; `fast` mode is the default.
- `colspan` for values shared by several columns: done. Layer 1 (one value per row) was measured and disabled by threshold (12/15 < 13/15); layer 2 (ruling-line geometry, `span_geometry = true`) is enabled after a measurement of 5/5 correct, 0 false (see `eval/table-spans.md`).
- Library queue and daemon: done.
- Obsidian-compatible output: `book.md` with frontmatter and a MOC note `<Name>.md`.
- Book summaries (no entity graph): `techbookocr summarize` writes `description`/`keywords` into the MOC and `summary` into meta.json, and builds `out/books-index.md`; the daemon summarizes after every book (`[library] auto_summarize`, model `[pipeline] summarizer_model`). A domain entity graph is postponed.
- OpenTUI panel: `techbookocr tui` launches the binary `panel/dist/techbookocr-tui` (Bun + OpenTUI, build with `cd panel && bun run build`), which talks to the core through `techbookocr bridge`. Screens Queue / Book / Telemetry / Settings; keys are in `panel/README.md` and `docs/guide.md`. The earlier Textual panel was removed.
- The project was renamed from `bookocr` to `techbookocr` throughout (package, CLI, config `techbookocr.toml`, containers `techbookocr-*`, dictionary cache `~/.cache/techbookocr/hunspell`, panel `techbookocr-tui`, variables `TECHBOOKOCR_TUI`/`TECHBOOKOCR_CMD`). Data formats (`library.sqlite`, `state.sqlite`, `out/<book>/`, `meta.json`) did not change.

Documents: the operations guide is `docs/guide.md`; model decisions are in `eval/recommendation.md`, golden-set metrics in `eval/cascade-report.md`, and **unresolved recognition problems are in `docs/known-issues.md`** (the main one: a value shared by several columns is attributed to a single column).
