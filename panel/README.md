# techbookocr-tui

Terminal control panel for the `techbookocr` book-recognition library: queue, per-book stages and `quality.md`, GPU/throughput telemetry, settings, and daemon control. Built with [OpenTUI](https://opentui.com) (Bun + Solid) and compiled to a single binary. All data and commands go through the Python core: `techbookocr bridge` (JSON lines on stdin/stdout, protocol v1, see `src/techbookocr/tui/bridge.py`).

## Requirements

- Linux x64 (glibc), a UTF-8 terminal, at least 80x24 (below that the panel shows only "window too small").
- The `techbookocr` core: found via `techbookocr tui` (which passes itself), `--bridge-cmd`, `$TECHBOOKOCR_CMD`, or `techbookocr` on `PATH`.
- To build: [Bun](https://bun.sh) >= 1.3.

## Installation

```bash
curl -fsSL https://bun.sh/install | bash
cd panel && bun install && bun run build      # -> panel/dist/techbookocr-tui
```

`bun run build` runs `bun build --compile` for `bun-linux-x64` with `--define process.env.OPENTUI_LIBC='"glibc"'`. `@opentui/*` versions are pinned exactly (0.5.14); `bun.lock` is committed.

## Quick Start

```bash
uv run techbookocr tui                      # finds panel/dist/techbookocr-tui and execs it
uv run techbookocr tui --out out --config techbookocr.toml
panel/dist/techbookocr-tui --bridge-cmd "uv run techbookocr" --out out    # direct start
```

`techbookocr tui` looks for the binary in `$TECHBOOKOCR_TUI`, then `panel/dist/techbookocr-tui` of the repository, then `techbookocr-tui` on `PATH`. It passes `--bridge-cmd` (shell-quoted) so the panel talks to the same Python environment. Quitting the panel (`q`, `Ctrl+C`) never stops the daemon.

## Configuration

| Option | Meaning |
|---|---|
| `--out <dir>` | library root (default: `[library] dir` from the config) |
| `--config <file>` | `techbookocr.toml` to use; the panel also passes it to `techbookocr daemon` when you press `d` |
| `--bridge-cmd <cmd>` | command that starts the core (shell-quoted); default `$TECHBOOKOCR_CMD`, then `techbookocr` from `PATH` |
| `TECHBOOKOCR_TUI` | (for `techbookocr tui`) path to the panel binary |
| `NO_COLOR`, `TERM=dumb` | no colour, only bold/dim/reverse |

Everything else is edited in the Settings screen (`4`), which rewrites `techbookocr.toml` line by line and keeps comments and unrelated keys. Changing `library.dir` switches the panel to the new library immediately.

## Keyboard Shortcuts

Hotkeys also work on the Russian JCUKEN layout (the same physical keys). `Ctrl+C` quits everywhere.

| Where | Keys |
|---|---|
| Everywhere | `1-4` screens, `?` help, `q` quit (the daemon keeps running), `Ctrl+C` quit |
| Queue | `Up/Down` or `j/k` move, `Space` mark, `c` clear marks, `Enter` open Book, `a` add books, `x` run, `s` skip, `r` retry, `+`/`-` priority, `/` filter, `f` review misprint fixes |
| Daemon (Queue, Book, Telemetry) | `d` start, `p` pause/resume, `t` stop (asks for confirmation) |
| Book | `Tab` switch pane, `o` open folder, `r`/`s` retry/skip, `f` review misprint fixes, `Esc` back |
| Fixes | `Up/Down` or `j/k` move, `PgUp/PgDn` page, `Space` toggle fix ⇄ printed text, `Enter` keep (clear ?), `n` next to review, `/` filter, `m` readable / raw math, `Esc` back |
| Settings | `Up/Down` field, `Left/Right` value, `Enter` edit number/path, `Ctrl+S` save, `e` open in `$EDITOR`, `Esc` discard |
| Add books | `Up/Down` move, `Space` mark a file or a folder (a folder is added recursively), `Enter` open folder / add marked (or the current file), `a` add the marked files and folders (or the entry under the cursor, whatever it is), `Backspace` parent folder (cursor lands on the folder you came from), `Esc` cancel |
| Help | `Up/Down` scroll, `Esc`/`?`/`q` close |

The footer shows the 5-7 most useful keys of the current screen on the left and the daemon group on the right; `?` lists everything. Toasts (results of actions, errors) appear in the footer line. The selection follows the book across refreshes; marks survive snapshot updates and, in Add books, folder changes. Add books follows symlinks to folders and books.

## Terminal Compatibility

- Required: a TTY, UTF-8, 80x24 or larger. The book card on Queue appears from width 110.
- Enhanced: truecolor. `NO_COLOR` / `TERM=dumb` disable colour; status is always an icon plus a word (`▸ processing`, `· queued`, `✓ done`, `✗ failed`, `– skipped`).
- Mouse is not needed (everything works from the keyboard); only scrolling comes for free from OpenTUI.
- Right-to-left scripts are not supported (the library holds ru/en/de books).
- The terminal is restored on every exit path (`q`, `Ctrl+C`, SIGTERM, exceptions).

## Troubleshooting

- **"reconnecting… (attempt n)"**: the core crashed or timed out. Run the bridge by hand and watch stderr: `uv run techbookocr bridge --out out`, then type `{"id":1,"op":"snapshot"}`. A broken `techbookocr.toml` makes the bridge refuse to start; the banner shows the parser error.
- **"techbookocr core not found"** (exit code 2): pass `--bridge-cmd`, set `TECHBOOKOCR_CMD`, or put `techbookocr` on `PATH`.
- **`techbookocr tui` says "techbookocr-tui not found"**: build it (see Installation) or set `TECHBOOKOCR_TUI`.
- **Terminal looks broken after a crash**: run `reset`.
- **"daemon failed to start"**: read `<library>/daemon.log`.

## Development

```bash
cd panel
bun install
bun run dev          # run from sources (needs --bridge-cmd / TECHBOOKOCR_CMD)
bun run typecheck    # tsc --noEmit
bun run build        # compiled binary in dist/
```

Layout: `src/bridge` (client, protocol), `src/state` (store, keys, selection), `src/screens` and `src/components` (Solid views), `src/effects.ts` (commands to the bridge), `test/` (bun tests and frame snapshots).

## Testing

```bash
cd panel && bun test                      # logic, bridge client against a fake bridge, frames at 120x35 / 80x24 / NO_COLOR
bun test --update-snapshots               # after an intentional UI change
uv run pytest -q tests/tui                # Python side: bridge, actions, snapshots
```

The protocol is defined in `src/techbookocr/tui/bridge.py`. Before trusting a build, run the compiled binary against a temporary library (not only `bun test`): `--compile` has known OpenTUI regressions with markdown rendering, so the Book screen with `quality.md` is part of the smoke check.
