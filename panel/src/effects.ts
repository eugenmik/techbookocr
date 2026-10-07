// Executes reducer commands: bridge requests, file system, xdg-open, $EDITOR.
// Any error → toast, not an exception.
import { existsSync, readdirSync, statSync } from "node:fs"
import { basename, join } from "node:path"
import type { BridgeLike } from "./bridge/client"
import type { ActResult, AddResult, BookDetail, Fix, FixCounts, FixesData, SettingsData, Snapshot } from "./bridge/types"
import { splitWords } from "./shell"
import type { Action, Command, DirEntry } from "./state/store"

export interface EffectCtx { client: BridgeLike; now: () => number; suspend?: (fn: () => void) => void }

// A large add (hundreds of files, folder traversal) does not fit into the usual 10 s request timeout.
const ADD_TIMEOUT_MS = 120_000
// The first open of an older book's fixes builds the journal and loads the hunspell dictionary: seconds.
const FIXES_TIMEOUT_MS = 60_000

// Settings replies carry the library root: when library.dir changes, subsequent bridge launches take it as --out.
async function settings(ctx: EffectCtx): Promise<SettingsData> {
  const data = await ctx.client.request<SettingsData>("settings_get")
  if (data.root) ctx.client.retarget(data.root)
  return data
}

const BOOK_EXT = /\.(djvu|pdf)$/i

// Python actions (src/techbookocr/tui/actions.py) return plain strings; errors are recognized by the string prefix.
export const ERROR_MESSAGE = /^(error\b|no book\b|not added\b|daemon failed\b|daemon not started\b|cannot\b|unknown\b)/i

export function messageLevel(msg: string): "info" | "error" {
  return ERROR_MESSAGE.test(msg) || msg.includes(" rejected") ? "error" : "info"
}

export function listDir(dir: string): DirEntry[] {
  const out: DirEntry[] = []
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name.startsWith(".")) continue
    let isDir = e.isDirectory(), isFile = e.isFile()
    if (e.isSymbolicLink()) {                      // symlink: decide by the target; broken ones are skipped
      try { const st = statSync(join(dir, e.name)); isDir = st.isDirectory(); isFile = st.isFile() } catch { continue }
    }
    if (isDir) out.push({ name: e.name, dir: true })
    else if (isFile && BOOK_EXT.test(e.name)) out.push({ name: e.name, dir: false })
  }
  return out.sort((a, b) => (a.dir === b.dir ? a.name.localeCompare(b.name) : a.dir ? -1 : 1))
}

export async function runCommand(cmd: Command, ctx: EffectCtx): Promise<Action[]> {
  const toast = (text: string, level: "info" | "error" = "info"): Action => ({ type: "toast", text, level, now: ctx.now() })
  try {
    switch (cmd.kind) {
      case "snapshot":
        return [{ type: "snapshot", snap: await ctx.client.request<Snapshot>("snapshot"), now: ctx.now() }]
      case "act": {
        const r = await ctx.client.request<ActResult>("act", { action: cmd.action, books: cmd.books ?? [], delta: cmd.delta })
        return [...r.messages.map((m) => toast(m, messageLevel(m))), { type: "poll" }]
      }
      case "add": {
        const r = await ctx.client.request<AddResult>("add", { paths: cmd.paths }, { timeoutMs: ADD_TIMEOUT_MS })
        return [...r.messages.map((m) => toast(m, messageLevel(m))), { type: "poll" }]
      }
      case "loadBook":
        return [{ type: "bookLoaded", detail: await ctx.client.request<BookDetail>("book", { name: cmd.name }) }]
      case "loadSettings":
        return [{ type: "settingsLoaded", data: await settings(ctx) }]
      case "saveSettings": {
        const saved = await ctx.client.request<{ root?: string }>("settings_set", { updates: cmd.updates })
        if (saved?.root) ctx.client.retarget(saved.root)
        return [toast("settings saved"), { type: "settingsLoaded", data: await settings(ctx) },
                { type: "poll" }]
      }
      case "editToml": {
        const editor = process.env.VISUAL || process.env.EDITOR || "nano"
        if (!ctx.suspend) return [toast(`edit ${cmd.path} in your editor, then reopen Settings`)]
        const argv = splitWords(editor)             // "code --wait" is a command with arguments
        ctx.suspend(() => { Bun.spawnSync([...argv, cmd.path], { stdio: ["inherit", "inherit", "inherit"] }) })
        return [{ type: "settingsLoaded", data: await settings(ctx) }]
      }
      case "openFolder":
        Bun.spawn(["xdg-open", cmd.path], { stdout: "ignore", stderr: "ignore" })
        return [toast(`opened ${cmd.path}`)]
      case "openFile":
        // fixes/ may not have been copied or may be deleted: xdg-open would stay silent, so say it here
        if (!existsSync(cmd.path)) return [toast(`scan fragment missing: ${cmd.path}`, "error")]
        Bun.spawn(["xdg-open", cmd.path], { stdout: "ignore", stderr: "ignore" })
        return [toast(`opened ${basename(cmd.path)}`)]
      case "listDir":
        return [{ type: "dirListed", dir: cmd.dir, entries: listDir(cmd.dir), focus: cmd.focus }]
      case "log":
        return [{ type: "log", lines: (await ctx.client.request<{ lines: string[] }>("log_tail", { lines: cmd.lines })).lines }]
      case "loadFixes":
        return [{ type: "fixesLoaded", book: cmd.book,
                  data: await ctx.client.request<FixesData>("fixes", { book: cmd.book }, { timeoutMs: FIXES_TIMEOUT_MS }) }]
      case "fixSet": {
        const r = await ctx.client.request<{ fix: Fix; counts: FixCounts }>("fix_set", { book: cmd.book, fix: cmd.id, applied: cmd.applied })
        return [{ type: "fixUpdated", book: cmd.book, fix: r.fix, counts: r.counts },
                toast(cmd.applied ? `${cmd.id}: fix applied` : `${cmd.id}: printed text restored`)]
      }
      case "fixKeep": {
        const r = await ctx.client.request<{ fix: Fix; counts: FixCounts }>("fix_keep", { book: cmd.book, fix: cmd.id })
        return [{ type: "fixUpdated", book: cmd.book, fix: r.fix, counts: r.counts }]
      }
      case "notify":
        return [toast(cmd.text, cmd.level)]
      case "quit":
        return []
    }
  } catch (e) {
    const msg = (e as Error).message
    if (cmd.kind === "snapshot") return [{ type: "stale" }]
    // Loading the fixes failed: the screen must not wait forever, so besides the toast it gets the error text.
    if (cmd.kind === "loadFixes") return [toast(msg, "error"), { type: "fixesFailed", book: cmd.book, error: msg }]
    // fix_set/fix_keep refused (the fix's place changed, the book is processing…): the bridge has already corrected the journal,
    // so reload it to let the screen show not_found and the like. If the reload fails, only the toast remains.
    if (cmd.kind === "fixSet" || cmd.kind === "fixKeep") {
      try {
        const data = await ctx.client.request<FixesData>("fixes", { book: cmd.book }, { timeoutMs: FIXES_TIMEOUT_MS })
        return [toast(msg, "error"), { type: "fixesLoaded", book: cmd.book, data }]
      } catch { /* bridge unavailable: the toast about the original error is enough */ }
    }
    return [toast(msg, "error")]
  }
}
