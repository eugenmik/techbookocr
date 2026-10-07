# Guide: book recognition and the TUI panel

How to queue books, start processing, monitor it, and move the result into Obsidian.

## Typical workflow

```bash
uv run techbookocr add ~/books/foundry test_books/atlas.djvu   # 1. books -> queue
uv run techbookocr tui                                      # 2. open the panel
# in the panel: press d to start the daemon              # 3. processing begins
```

The daemon takes books from the queue one at a time (by priority, then by time added) and runs each through all pipeline stages. You can close the panel (`q`) and the daemon keeps working; reopen it and everything is still there. All state lives in `out/library.sqlite`; the panel and the commands go only through it.

A single 300–500 page book takes hours to process; a library takes days or weeks. That is normal: everything is resumable.

## Preparation

- **Input:** `.djvu` and `.pdf` files anywhere on disk; they do not have to be in `test_books/`. Folders passed to `add` are traversed recursively.
- **Config:** `techbookocr.toml`. Mode is `[pipeline] mode = "fast"` (the default; `cascade` is about 2.5 times slower with the same quality). The library root is `[library] dir = "out"`.
- **GPU:** only one model fits in VRAM at a time. The daemon stops one model's container before starting the next, but **do not run** `techbookocr run`, `eval`, or a second daemon in parallel. They will kill the other process's container.
- **First model launch:** the docker image and weights are downloaded from the network; set `HF_HUB_DISABLE_XET=1`, otherwise Hugging Face downloads get interrupted.

## Queue commands (terminal)

```bash
uv run techbookocr add <file|folder> [more paths...]   # enqueue; duplicate paths and names are skipped
uv run techbookocr daemon                           # process the queue (in this terminal, Ctrl+C stops)
uv run techbookocr status                           # daemon, counts by status, latest events
uv run techbookocr pause / resume / stop            # commands to a live daemon
uv run techbookocr skip <name>                      # drop a book (queued -> skipped; if in progress, abort it)
uv run techbookocr retry <name>                     # return failed/skipped to the queue
uv run techbookocr priority <name> <number>         # higher means earlier in the queue (default 0)
uv run techbookocr summarize <name> [--all] [--redo] # model-written book summary -> preview in MOC + library index
uv run techbookocr fixes <book> [--revert ID | --apply ID | --keep ID]   # misprint fixes: list, revert, apply, keep (one action at a time)
```

`techbookocr summarize` appends the `description`/`keywords` fields and a preview paragraph to `<Name>.md`, a `summary` block to `meta.json`, and rebuilds `out/books-index.md`, the root note with one line per book. The daemon does this itself after each assembled book (`[library] auto_summarize`); for books recognized earlier, use `summarize --all`. The model is `[pipeline] summarizer_model`, by default the same local qwen9b as the arbiter.

`--out <folder>` and `--config <toml>` are available in every command if the library or config is non-standard.

Important: `pause`/`resume`/`stop` work **only with a live daemon**. With a dead daemon the command is not recorded (the output says so plainly). `skip`/`retry`/`priority` apply immediately when the daemon is dead; when it is alive, they go into the command queue and the daemon executes them between model requests.

## TUI panel

```bash
cd panel && bun install && bun run build   # once: panel -> panel/dist/techbookocr-tui
uv run techbookocr tui                         # open the panel (--out, --config work as in other commands)
```

The `techbookocr-tui` panel (Bun + OpenTUI) is a separate binary; `techbookocr tui` looks for it in `$TECHBOOKOCR_TUI`, then in `panel/dist/techbookocr-tui`, then in `PATH`, and launches it, passing the core (`--bridge-cmd`). Data and commands go through `techbookocr bridge` (JSON lines). The interface is in English. Minimum window is 80×24; the book card on Queue is visible at widths of 110 and up. For installation details, terminal compatibility, and debugging, see `panel/README.md`.

At the top is a status line: daemon state (`● running`, `◌ paused`, `○ stopped`, stage), queue size and forecast, GPU; with a dead daemon and a non-empty queue, the hint `→ press d to start`; on the right, the library root. Below are the tabs: **1 Queue · 2 Book · 3 Telemetry · 4 Settings**. At the bottom is a footer: 5–7 keys of the current screen on the left and the daemon group (`d start  p pause  t stop`) on the right; action results (toasts) appear on the same line.

Book status is an icon plus a word: `▸ processing`, `· queued`, `✓ done`, `✗ failed`, `– skipped`. `NO_COLOR` or `TERM=dumb` disables color. When the bridge drops, a yellow banner `reconnecting… (attempt n)` appears, the last data stays on screen, and the bridge restarts by itself.

**Queue** is a table of books (mark `●`, name, status, stage/progress, priority `p<n>`, error); on the right is a card for the selected book (stages, quality, error); at the bottom are the latest library events. The selection follows the book across refreshes, and so do the marks.

**Book** (`Enter` on Queue or `2`) shows stages on the left with time, sec/page and ETA, and the list of problems; on the right is the book's `quality.md` as scrollable markdown. `Tab` switches the column, `o` opens the book's folder, `f` opens the Fixes screen, `Esc` goes back.

**Fixes** (`f` on Queue or Book) lists the arbiter's misprint fixes from `quality.md`, one line each with an icon: `✓` applied, `↶` reverted to the printed text (by a rule or by hand), `?` doubtful (the dictionary rule; waiting for a decision), `·` not found in `book.md`. Formula markup (`<sub>`, `<sup>`, LaTeX) in the list and the context is shown in readable form: `σ₋₁ₚ`, `10⁻⁶`, `α ≤ 5°`, `(a+b)/c`. If the readable forms of "was" and "now" are the same (the fix shows only in the markup), the line is shown as it is. The book and the journal do not change. The context of the fix from `book.md` is shown below the list. Keys: `Space` toggles "now ⇄ was" directly in `book.md`, `Enter` keeps the fix as it is and clears the `?`, `n` jumps to the next fix to review, `/` cycles the filter, `m` switches formulas between readable and raw markup, `PgUp`/`PgDn` move by 10 lines, `Esc` goes back. A manual revert is recorded in `out/rejected-fixes.json`, and the same fix (the "was → now" pair) is reverted automatically in later books. An older book (without `fixes.json`) is brought up to the current checking rules when it is first opened, either on the Fixes screen or with a plain `techbookocr fixes <book>`: fixes rejected by the unambiguous rules (values, operators, element symbols and so on) and the pairs in `rejected-fixes.json` are reverted in `book.md` to the printed text; the dictionary rule only sets `?` and leaves the text alone. A fix whose place in `book.md` cannot be found unambiguously, and an insertion or deletion of text (an empty "was" or "now"), gets `·` and cannot be toggled. While the book is in progress (`processing`), the journal is read-only (`techbookocr fixes` prints the list marked `read-only` and writes nothing).

Rebuilding a reviewed book (`run --keep-work --redo postproc` or `--redo assemble`, `run --models`) assembles `book.md` again from the `work/` state, and manual reverts made on the Fixes screen are lost. The pairs stay in `rejected-fixes.json` and apply to books that pass the arbiter after the revert.

**Telemetry** (`3`) shows GPU charts (memory, utilization) and throughput since the panel was opened, the model in the container, and the tail of `daemon.log` (`PgUp`/`PgDn`).

**Settings** (`4`) edits `techbookocr.toml` (or the file from `--config`):

| Field | Key |
|------|------|
| mode | `[pipeline] mode` (fast/cascade) |
| summarizer_model | `[pipeline] summarizer_model` |
| sketches_device, webp_quality, text_layer | `[pipeline] …` |
| dir | `[library] dir` |
| auto_summarize, command_poll_s, idle_poll_s | `[library] …` |
| min_dpi, max_dpi, split_spreads | `[render] …` |

`←→` changes a value from a list, `Enter` edits a number or path, `Ctrl+S` saves the file line by line (comments and other keys are preserved), `e` opens the raw `techbookocr.toml` in `$EDITOR` (for keys that are not in the form; after editing, the panel rereads the file on return; if the TOML is broken, the panel shows an error in a red toast and the values do not update, so fix the file and press `e` again), `Esc` discards unsaved edits. If `library.dir` changes, the panel reconnects to the new library on the fly (the daemon of the old root keeps doing its work).

### Starting recognition

A queued book is not processed by itself; a daemon is needed. Three scenarios:

- **One book:** cursor on the book, then `x`. The book gets top priority, the daemon starts by itself (if dead), processes it, and pauses (run_until), leaving the rest of the queue untouched. A failed book is first returned to the queue (retry). If the book is already processing and the daemon is paused, `x` lifts the pause and sets run_until on it.
- **Several books (bulk):** `Space` marks rows (the cursor moves down), then `x`. All marked books run in sequence at the top of the queue, with a pause after the last one.
- **Whole queue:** `d` is a full run without a pause (clears run_until; on a paused daemon it does resume).

### Keys

Hotkeys also work on the Russian JCUKEN layout (same physical keys). `Ctrl+C` exits from anywhere.

| Where | Keys |
|---|---|
| Everywhere | `1–4` screens · `?` help (scrollable) · `q` quit (the daemon keeps running) · `Ctrl+C` quit |
| Queue | `↑↓`/`j k` move · `Space` mark · `c` clear marks · `Enter` → Book · `a` add · `x` run · `s` skip · `r` retry · `+`/`-` priority · `/` filter · `f` misprint fixes |
| Daemon (Queue, Book, Telemetry) | `d` start · `p` pause/resume (takes effect between model requests) · `t` stop (with `y`/`n` confirmation; a book in progress returns to the queue and stays resumable) |
| Book | `Tab` column · `o` folder · `r`/`s` · `f` misprint fixes · `Esc` back |
| Fixes | `↑↓`/`j k` move · `PgUp`/`PgDn` page · `Space` now ⇄ was · `Enter` keep (clear `?`) · `n` next to review · `/` filter · `m` readable ⇄ raw formulas · `Esc` back |
| Settings | `↑↓` field · `←→` value · `Enter` edit · `Ctrl+S` save · `e` $EDITOR · `Esc` discard |
| Add books | `↑↓` move · `Space` mark a file or folder · `Enter` on a directory enters it, on a file adds the marked items (or the current file) · `a` adds the marked items (or the entry under the cursor, file or folder), whatever is under the cursor · `Backspace` up (the cursor lands on the folder you came from) · `Esc` cancel |

**Add books (`a`)** opens at the home directory: directories first, files only `.djvu`/`.pdf`; symbolic links to folders and books are visible. Marks persist when moving between folders, so you can collect books from different directories in one go; a marked folder is added whole, recursively (`Space` on the folder, then `a`). The result is a message `added N, skipped M`; if the daemon is not running, the same message hints to press `d`.

Book names come from file names without the extension. The keys `s`/`r`/`+`/`-`/`a`/`x` work on Queue (`r`/`s` also on Book); `d`/`p`/`t` work on Queue, Book, and Telemetry; `q` works everywhere.

## A single book without the queue

```bash
uv run techbookocr run "test_books/book.djvu"            # into out/<book>/
uv run techbookocr run "..." --scans 0-39 --out out/trial # a fragment into a separate folder
uv run techbookocr run "..." --models                     # born-digital PDF: model pass
uv run techbookocr run "..." --redo arbiter               # recompute the stage and all following ones
```

Any repeated `run` resumes where it stopped; state is in `out/<book>/work/state.sqlite`. Interrupting with Ctrl+C is safe. After a successful assembly `work/` is deleted (renders and state are no longer needed); to keep it for debugging or `--redo`, use the `--keep-work` flag.

### PDFs with a text layer

A digitally typeset (born-digital) book is detected automatically: `[pipeline] text_layer = auto` probes the first pages, and if the layer is present on ≥70% of them and the layout is not multi-column, pages are not rasterized and no models are launched. Text, tables, and figures are extracted straight from the layer in minutes instead of hours of OCR.

The first `run` assembles `book.md` entirely without a GPU. Pages without a layer and tables with low reconstruction confidence remain in the queue; the second run, `run --models`, renders only those and runs the usual OCR stages. What is left to the models is visible in `quality.md` (section "Text-layer extraction") and in `meta.json.extraction`. To disable text-layer detection, use `text_layer = off`; to force it, `force`.

## Output and failures

```text
out/<book>/
  book.md          # text with frontmatter, HTML tables, LaTeX, figures, footnotes, page anchors
  <Name>.md        # MOC table of contents with links to headings (for books named "book"/"quality": <Name>-contents.md)
  images/          # cropped figures (WebP, quality is [pipeline] webp_quality, default 70)
  fixes.json       # misprint fix journal (the Fixes screen)
  quality.md       # what was corrected and what failed: typo fixes, failed blocks
  meta.json        # metadata and statistics (machine-readable source)
  work/            # state.sqlite, frames, crops: only while the book is in progress; deleted after assembly
out/library.sqlite, daemon.lock, daemon.log, library_report.md, books-index.md
out/rejected-fixes.json   # "was → now" pairs reverted by hand; applied to all books
```

- **A book does not fail as a whole** because of one block: a failed block falls back to the draft and is noted in `quality.md`.
- **Misprint fixes are checked** before they reach the book: fixes of values, operators, number indexes, element symbols, single Latin letters and the replacement of a dictionary word with another word are reverted to the printed text and appear in `quality.md` as `reverted: <reason>`. Pairs reverted by hand on the Fixes screen (`out/rejected-fixes.json`) are checked first and reverted with the reason `rejected by user`. The dictionary-word rule is turned off with `[pipeline] fix_reject_dictionary_words = false`.
- **A failed book** does not bring the daemon down; it moves on to the next one. A breakdown of all failed books is in `out/library_report.md`. After fixing the cause, run `retry`.
- **A model connection failure** (the server went down) does not corrupt the book: the stage is aborted and the book stays resumable; a restart continues from where it left off.
- `daemon.log` is the stdout/stderr of a daemon started from the panel; `daemon.lock` indicates that the daemon is alive.

## Moving to Obsidian

Copy into the vault: `book.md`, `<Name>.md`, `images/`, the root `books-index.md`; optionally `quality.md`.
Do not copy: `work/`, `meta.json`, `fixes.json`, the service files in the `out/` root (`library.sqlite`, `daemon.lock`, `daemon.log`, `rejected-fixes.json`).

In the vault a book looks like a note `<Name>` with a summary preview and a table of contents linking to the chapters of `book.md`; `books-index.md` is the entry point with a list of all books and descriptions. The frontmatter (`type: book-source`, `title`, `lang`, `pages`, `tags`, `description`, `keywords`) is visible in the properties panel; `author`/`year` and topic tags are filled in there by hand. Searching the vault finds a book by terms from `keywords`/`description`.
