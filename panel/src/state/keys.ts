// Key table is the single source of key behavior, the footer and the help.
// Dispatch order: modal → filter input → settings field edit → screen → daemon → global.
import { basename, dirname, join } from "node:path"
import type { FieldValue } from "../bridge/types"
import { queueLayout } from "../layout"
import { FILTERS, cursorIndex, nextReview, settleCursor, visibleFixes } from "./fixes"
import { fieldId, selectedName, targets, visibleBooks } from "./select"
import { LOG_LINES, relocate, syncSelection, type AppState, type Command, type KeyInput, type Result, type Screen } from "./store"

export type Scope = "global" | "daemon" | "queue" | "book" | "telemetry" | "settings" | "fixes" | "help" | "add" | "confirm"
export interface Binding { scope: Scope; keys: string[]; label: string; hint?: string; run: (s: AppState) => Result }

const ok = (state: AppState, ...cmds: Command[]): Result => ({ state, cmds })

// Russian JCUKEN layout → the key at the same position on the Latin layout: hotkeys work without switching layout.
const RU_KEYS: Record<string, string> = Object.fromEntries(
  [..."йцукенгшщзхъфывапролджэячсмитьбюё"].map((c, i) => [c, [..."qwertyuiop[]asdfghjkl;'zxcvbnm,.`"][i]]))

export function keyId(k: KeyInput): string {
  const seq = k.sequence
  if (!k.ctrl && !k.meta && seq && seq.length === 1 && seq > " " && seq !== "\x7f")
    return RU_KEYS[seq.toLocaleLowerCase()] ?? seq
  const name = k.name === "return" ? "enter" : k.name === "esc" ? "escape" : k.name
  return (k.ctrl ? "ctrl+" : "") + (k.meta ? "alt+" : "") + name
}

function move(s: AppState, delta: number): Result {
  return syncSelection({ ...s, cursor: s.cursor + delta })
}

function act(s: AppState, action: "skip" | "retry" | "run"): Result {
  const books = targets(s)
  if (!books.length) return ok(s)
  return ok({ ...s, marks: action === "run" ? [] : s.marks }, { kind: "act", action, books })
}

function bump(s: AppState, delta: number): Result {
  const books = targets(s)
  return books.length ? ok(s, { kind: "act", action: "bump", books, delta }) : ok(s)
}

export function goScreen(s: AppState, screen: Screen): Result {
  const st = { ...s, screen, modal: null }
  if (screen === "fixes") return openFixes(s)
  if (s.screen === screen) return ok(st)                  // already here: do not reload (the settings draft is alive)
  if (screen === "book") return st.bookName ? ok(st, { kind: "loadBook", name: st.bookName }) : ok(st)
  if (screen === "telemetry") return ok({ ...st, logScroll: 0 }, { kind: "log", lines: LOG_LINES })
  if (screen === "settings") return hasDraft(s) ? ok(st) : ok(st, { kind: "loadSettings" })   // do not overwrite the draft
  return ok(st)
}

// --- Fixes screen ---

function openFixes(s: AppState): Result {
  if (!s.bookName) return ok(s)
  const back = s.screen === "fixes" ? (s.fixes?.back ?? "book") : s.screen
  return ok({ ...s, screen: "fixes", modal: null, fixes: { book: s.bookName, data: null, cursorId: null, filter: "all", back, math: "readable" } },
            { kind: "loadFixes", book: s.bookName })
}

function fixesMove(s: AppState, d: number): Result {
  if (!s.fixes) return ok(s)
  const vis = visibleFixes(s.fixes)
  if (!vis.length) return ok(s)
  const i = Math.max(0, Math.min(vis.length - 1, cursorIndex(s.fixes) + d))
  return ok({ ...s, fixes: { ...s.fixes, cursorId: vis[i].id } })
}

function curFix(s: AppState) {
  return s.fixes?.data?.fixes.find((f) => f.id === s.fixes!.cursorId)
}

/** A "?" fix (applied but doubtful) was decided by a command: the cursor moves to the next "?"; if there is none, it stays. */
function stepReview(s: AppState, cmd: Command): Result {
  const next = nextReview(s.fixes!)
  return ok(next && next !== s.fixes!.cursorId ? { ...s, fixes: { ...s.fixes!, cursorId: next } } : s, cmd)
}

function fixToggle(s: AppState): Result {
  const f = curFix(s)
  if (!s.fixes?.data || !f) return ok(s)
  if (!s.fixes.data.editable) return ok(s, { kind: "notify", text: `read-only: ${s.fixes.data.why_not}`, level: "error" })
  if (f.state === "not_found") return ok(s, { kind: "notify", text: `${f.id}: not found in book.md — cannot toggle`, level: "error" })
  const cmd: Command = { kind: "fixSet", book: s.fixes.book, id: f.id, applied: f.state !== "applied" }
  return f.state === "applied" && f.suggested ? stepReview(s, cmd) : ok(s, cmd)
}

function fixKeep(s: AppState): Result {
  const f = curFix(s)
  if (!s.fixes?.data || !f) return ok(s)
  if (!s.fixes.data.editable) return ok(s, { kind: "notify", text: `read-only: ${s.fixes.data.why_not}`, level: "error" })
  return f.suggested ? stepReview(s, { kind: "fixKeep", book: s.fixes.book, id: f.id }) : ok(s)
}

/** Scan crop of the current fix in the system viewer. The book folder comes from the fixes reply, else from the open Book. */
function fixScan(s: AppState): Result {
  const f = curFix(s)
  if (!s.fixes?.data || !f) return ok(s)
  if (!f.crop) return ok(s, { kind: "notify", text: "no scan fragment (book assembled before this feature)", level: "info" })
  const dir = s.fixes.data.out_dir ?? (s.book?.info.name === s.fixes.book ? s.book.out_dir : undefined)
  if (!dir) return ok(s, { kind: "notify", text: "book folder unknown — reopen Fixes", level: "error" })
  return ok(s, { kind: "openFile", path: `${dir.replace(/\/+$/, "")}/${f.crop}` })
}

const hasDraft = (s: AppState) => Object.keys(s.settings?.draft ?? {}).length > 0

/** Quit; with unsaved settings, confirmation first. */
function quit(s: AppState): Result {
  if (!hasDraft(s)) return ok(s, { kind: "quit" })
  return ok({ ...s, modal: { kind: "confirm", text: "Discard unsaved settings and quit?", cmd: { kind: "quit" } } })
}

function toggleMark(s: AppState): Result {
  const n = selectedName(s)
  if (!n) return ok(s)
  const marks = s.marks.includes(n) ? s.marks.filter((m) => m !== n) : [...s.marks, n]
  return move({ ...s, marks }, 1)
}

// --- settings ---

function settingsField(s: AppState) {
  return s.settings ? s.settings.data.fields[s.settings.cursor] : undefined
}

function fieldValue(s: AppState, id: string, fallback: FieldValue): FieldValue {
  return s.settings && id in s.settings.draft ? s.settings.draft[id] : fallback
}

function cycle(s: AppState, dir: number): Result {
  const f = settingsField(s)
  if (!s.settings || !f) return ok(s)
  const id = fieldId(f)
  const cur = fieldValue(s, id, f.value)
  let next: FieldValue
  if (f.kind === "bool") next = !cur
  else if (f.choices.length) {
    const i = f.choices.indexOf(String(cur))
    next = f.choices[(i + dir + f.choices.length) % f.choices.length]
  } else return ok(s)
  const draft = { ...s.settings.draft }
  if (next === f.value) delete draft[id]
  else draft[id] = next
  return ok({ ...s, settings: { ...s.settings, draft, error: null } })
}

function startEdit(s: AppState): Result {
  const f = settingsField(s)
  if (!s.settings || !f || !["int", "float", "path"].includes(f.kind)) return cycle(s, 1)
  return ok({ ...s, settings: { ...s.settings, editing: String(fieldValue(s, fieldId(f), f.value) ?? "") } })
}

function commitEdit(s: AppState): Result {
  const f = settingsField(s)
  if (!s.settings || !f || s.settings.editing === null) return ok(s)
  const raw = s.settings.editing.trim()
  let v: FieldValue = raw
  if (f.kind === "int" || f.kind === "float") {
    const n = Number(raw)
    if (raw === "" || !Number.isFinite(n) || (f.kind === "int" && !Number.isInteger(n)))
      return ok({ ...s, settings: { ...s.settings, error: `${f.key}: not a${f.kind === "int" ? "n integer" : " number"}` } })
    v = n
  }
  const draft = { ...s.settings.draft }
  if (v === f.value) delete draft[fieldId(f)]
  else draft[fieldId(f)] = v
  return ok({ ...s, settings: { ...s.settings, draft, editing: null, error: null } })
}

function saveSettings(s: AppState): Result {
  if (!s.settings || !Object.keys(s.settings.draft).length) return ok(s)
  const updates = s.settings.data.fields
    .filter((f) => fieldId(f) in s.settings!.draft)
    .map((f) => ({ section: f.section, key: f.key, value: s.settings!.draft[fieldId(f)] }))
  return ok(s, { kind: "saveSettings", updates })
}

function settingsMove(s: AppState, d: number): Result {
  if (!s.settings) return ok(s)
  const n = s.settings.data.fields.length
  return ok({ ...s, settings: { ...s.settings, cursor: Math.max(0, Math.min(n - 1, s.settings.cursor + d)) } })
}

// --- Add books window ---

function addMove(s: AppState, d: number): Result {
  if (s.modal?.kind !== "add") return ok(s)
  const n = s.modal.entries.length
  return ok({ ...s, modal: { ...s.modal, cursor: Math.max(0, Math.min(n - 1, s.modal.cursor + d)) } })
}

function addEnter(s: AppState): Result {
  if (s.modal?.kind !== "add") return ok(s)
  const e = s.modal.entries[s.modal.cursor]
  if (e?.dir) return ok(s, { kind: "listDir", dir: join(s.modal.dir, e.name) })
  return addNow(s)
}

// `a`: add the marked entries (or the entry under the cursor, a file or folder), whatever is under the cursor.
function addNow(s: AppState): Result {
  if (s.modal?.kind !== "add") return ok(s)
  const e = s.modal.entries[s.modal.cursor]
  if (!s.modal.marked.length && e?.dir) {            // folder without marks: recursive add only after "y"
    const dir = join(s.modal.dir, e.name)
    return ok({ ...s, modal: { kind: "confirm", text: `Add every .djvu/.pdf under ${dir} (recursive)?`,
                               cmd: { kind: "add", paths: [dir] } } })
  }
  const paths = s.modal.marked.length ? s.modal.marked : e ? [join(s.modal.dir, e.name)] : []
  return paths.length ? ok({ ...s, modal: null }, { kind: "add", paths }) : ok(s)
}

function addMark(s: AppState): Result {
  if (s.modal?.kind !== "add") return ok(s)
  const e = s.modal.entries[s.modal.cursor]
  if (!e) return ok(s)
  const p = join(s.modal.dir, e.name)
  const marked = s.modal.marked.includes(p) ? s.modal.marked.filter((m) => m !== p) : [...s.modal.marked, p]
  return addMove({ ...s, modal: { ...s.modal, marked } }, 1)
}

const page = (s: AppState) => queueLayout(s.size.width, s.size.height).tableH

export const BINDINGS: Binding[] = [
  // global
  { scope: "global", keys: ["1"], label: "Queue screen", run: (s) => goScreen(s, "queue") },
  { scope: "global", keys: ["2"], label: "Book screen", run: (s) => goScreen(s, "book") },
  { scope: "global", keys: ["3"], label: "Telemetry screen", run: (s) => goScreen(s, "telemetry") },
  { scope: "global", keys: ["4"], label: "Settings screen", run: (s) => goScreen(s, "settings") },
  { scope: "global", keys: ["?"], label: "all keys", hint: "? keys", run: (s) => ok({ ...s, modal: { kind: "help" } }) },
  { scope: "global", keys: ["q", "ctrl+c"], label: "quit (daemon keeps running)", run: quit },
  // daemon: on Queue, Book, Telemetry
  { scope: "daemon", keys: ["d"], label: "start daemon (whole queue)", hint: "d start",
    run: (s) => ok(s, { kind: "act", action: "daemon_start" }) },
  { scope: "daemon", keys: ["p"], label: "pause / resume daemon", hint: "p pause",
    run: (s) => ok(s, { kind: "act", action: "daemon_toggle" }) },
  { scope: "daemon", keys: ["t"], label: "stop daemon", hint: "t stop",
    run: (s) => ok({ ...s, modal: { kind: "confirm", text: "Stop the daemon? The current book stays resumable.",
                                    cmd: { kind: "act", action: "daemon_stop" } } }) },
  // Queue
  { scope: "queue", keys: ["up", "k"], label: "move up", hint: "↑↓ move", run: (s) => move(s, -1) },
  { scope: "queue", keys: ["down", "j"], label: "move down", run: (s) => move(s, 1) },
  { scope: "queue", keys: ["pageup"], label: "page up", run: (s) => move(s, -page(s)) },
  { scope: "queue", keys: ["pagedown"], label: "page down", run: (s) => move(s, page(s)) },
  { scope: "queue", keys: ["enter"], label: "open book", hint: "⏎ open", run: (s) => goScreen(s, "book") },
  { scope: "queue", keys: ["space"], label: "mark / unmark", hint: "␣ mark", run: toggleMark },
  { scope: "queue", keys: ["c"], label: "clear marks", run: (s) => ok({ ...s, marks: [] }) },
  { scope: "queue", keys: ["a"], label: "add books", hint: "a add",
    run: (s) => ok({ ...s, modal: { kind: "add", dir: process.env.HOME ?? "/", entries: [], cursor: 0, marked: [] } },
                   { kind: "listDir", dir: process.env.HOME ?? "/" }) },
  { scope: "queue", keys: ["x"], label: "run selected now", hint: "x run", run: (s) => act(s, "run") },
  { scope: "queue", keys: ["s"], label: "skip", run: (s) => act(s, "skip") },
  { scope: "queue", keys: ["r"], label: "retry", run: (s) => act(s, "retry") },
  { scope: "queue", keys: ["+", "="], label: "priority +1", run: (s) => bump(s, 1) },
  { scope: "queue", keys: ["-"], label: "priority −1", run: (s) => bump(s, -1) },
  { scope: "queue", keys: ["/"], label: "filter by name", hint: "/ filter",
    run: (s) => ok({ ...s, filter: { active: true, text: s.filter.text } }) },
  // Book
  { scope: "book", keys: ["tab"], label: "switch pane", hint: "Tab pane",
    run: (s) => ok({ ...s, bookPane: s.bookPane === "stages" ? "quality" : "stages" }) },
  { scope: "book", keys: ["o"], label: "open book folder", hint: "o folder",
    run: (s) => (s.book ? ok(s, { kind: "openFolder", path: s.book.out_dir }) : ok(s)) },
  { scope: "book", keys: ["r"], label: "retry", hint: "r retry",
    run: (s) => (s.bookName ? ok(s, { kind: "act", action: "retry", books: [s.bookName] }) : ok(s)) },
  { scope: "book", keys: ["s"], label: "skip", hint: "s skip",
    run: (s) => (s.bookName ? ok(s, { kind: "act", action: "skip", books: [s.bookName] }) : ok(s)) },
  { scope: "book", keys: ["escape"], label: "back to queue", hint: "esc back", run: (s) => goScreen(s, "queue") },
  { scope: "queue", keys: ["f"], label: "review misprint fixes", hint: "f fixes", run: openFixes },
  { scope: "book", keys: ["f"], label: "review misprint fixes", hint: "f fixes", run: openFixes },
  // Fixes
  { scope: "fixes", keys: ["up", "k"], label: "move up", hint: "↑↓ move", run: (s) => fixesMove(s, -1) },
  { scope: "fixes", keys: ["down", "j"], label: "move down", run: (s) => fixesMove(s, 1) },
  { scope: "fixes", keys: ["pageup"], label: "page up", run: (s) => fixesMove(s, -10) },
  { scope: "fixes", keys: ["pagedown"], label: "page down", run: (s) => fixesMove(s, 10) },
  { scope: "fixes", keys: ["space"], label: "toggle fix ⇄ printed text", hint: "␣ toggle", run: fixToggle },
  { scope: "fixes", keys: ["enter"], label: "keep as is (clear ?)", hint: "⏎ keep", run: fixKeep },
  { scope: "fixes", keys: ["n"], label: "next fix to review", hint: "n next ?",
    run: (s) => { const id = s.fixes ? nextReview(s.fixes) : null
                  return id ? ok({ ...s, fixes: { ...s.fixes!, filter: "all", cursorId: id } }) : ok(s) } },
  { scope: "fixes", keys: ["/"], label: "filter: all / to review / applied / printed / not found", hint: "/ filter",
    run: (s) => { if (!s.fixes) return ok(s)
                  const filter = FILTERS[(FILTERS.indexOf(s.fixes.filter) + 1) % FILTERS.length]
                  return ok({ ...s, fixes: settleCursor({ ...s.fixes, filter }) }) } },
  { scope: "fixes", keys: ["v"], label: "open the scan fragment", hint: "v scan", run: fixScan },
  { scope: "fixes", keys: ["m"], label: "toggle readable / raw math", hint: "m math",
    run: (s) => s.fixes ? ok({ ...s, fixes: { ...s.fixes, math: (s.fixes.math ?? "readable") === "raw" ? "readable" : "raw" } }) : ok(s) },
  { scope: "fixes", keys: ["escape"], label: "back", hint: "esc back", run: (s) => goScreen(s, s.fixes?.back ?? "book") },
  // Telemetry
  { scope: "telemetry", keys: ["pageup"], label: "scroll log up", hint: "PgUp/PgDn log",
    run: (s) => ok({ ...s, logScroll: Math.min(Math.max(0, s.log.length - 1), s.logScroll + 10) }) },
  { scope: "telemetry", keys: ["pagedown"], label: "scroll log down",
    run: (s) => ok({ ...s, logScroll: Math.max(0, s.logScroll - 10) }) },
  // Settings
  { scope: "settings", keys: ["up", "k"], label: "previous field", hint: "↑↓ field", run: (s) => settingsMove(s, -1) },
  { scope: "settings", keys: ["down", "j"], label: "next field", run: (s) => settingsMove(s, 1) },
  { scope: "settings", keys: ["left", "h"], label: "previous value", hint: "←→ value", run: (s) => cycle(s, -1) },
  { scope: "settings", keys: ["right", "l"], label: "next value", run: (s) => cycle(s, 1) },
  { scope: "settings", keys: ["enter"], label: "edit number / path", hint: "⏎ edit", run: startEdit },
  { scope: "settings", keys: ["ctrl+s"], label: "save", hint: "^S save", run: saveSettings },
  { scope: "settings", keys: ["e"], label: "open techbookocr.toml in $EDITOR", hint: "e $EDITOR",
    run: (s) => (s.settings ? ok(s, { kind: "editToml", path: s.settings.data.path }) : ok(s)) },
  { scope: "settings", keys: ["escape"], label: "discard changes", hint: "esc discard",
    run: (s) => (s.settings ? ok({ ...s, settings: { ...s.settings, draft: {}, error: null } }) : ok(s)) },
  // modal windows
  { scope: "help", keys: ["escape", "?", "q"], label: "close", hint: "esc close", run: (s) => ok({ ...s, modal: null }) },
  { scope: "confirm", keys: ["y"], label: "yes", hint: "y yes",
    run: (s) => (s.modal?.kind === "confirm" ? ok({ ...s, modal: null }, s.modal.cmd) : ok(s)) },
  { scope: "confirm", keys: ["n", "escape"], label: "no", hint: "n no", run: (s) => ok({ ...s, modal: null }) },
  { scope: "add", keys: ["up", "k"], label: "move up", hint: "↑↓ move", run: (s) => addMove(s, -1) },
  { scope: "add", keys: ["down", "j"], label: "move down", run: (s) => addMove(s, 1) },
  { scope: "add", keys: ["space"], label: "mark file or folder", hint: "␣ mark", run: addMark },
  { scope: "add", keys: ["enter"], label: "open folder / add marked", hint: "⏎ open/add", run: addEnter },
  { scope: "add", keys: ["a"], label: "add marked (or the entry under the cursor)", hint: "a add", run: addNow },
  { scope: "add", keys: ["backspace"], label: "parent folder", hint: "⌫ up",
    run: (s) => (s.modal?.kind === "add" ? ok(s, { kind: "listDir", dir: dirname(s.modal.dir), focus: basename(s.modal.dir) }) : ok(s)) },
  { scope: "add", keys: ["escape"], label: "cancel", hint: "esc cancel", run: (s) => ok({ ...s, modal: null }) },
]

function scopes(s: AppState): Scope[] {
  if (s.modal) return [s.modal.kind]
  const daemon: Scope[] = s.screen === "settings" || s.screen === "fixes" ? [] : ["daemon"]
  return [s.screen, ...daemon, "global"]
}

function textInput(text: string, k: KeyInput, id: string): string | null {
  if (id === "backspace") return text.slice(0, -1)
  if (!k.ctrl && !k.meta && k.sequence && !k.sequence.startsWith("\x1b")) {
    const clean = k.sequence.replace(/[\x00-\x1f\x7f]/g, "")   // paste: without control characters
    return clean ? text + clean : null
  }
  return null
}

export function handleKey(s: AppState, k: KeyInput): Result {
  const id = keyId(k)
  if (id === "ctrl+c")                                       // quit from anywhere; with a draft one confirmation,
    return s.modal?.kind === "confirm" ? ok(s, { kind: "quit" }) : quit(s)   // a second ctrl+c in it quits
  if (!s.modal && s.screen === "queue" && s.filter.active) {
    if (id === "enter") return relocate({ ...s, filter: { active: false, text: s.filter.text } })
    if (id === "escape") return relocate({ ...s, filter: { active: false, text: "" } }, 0)
    const t = textInput(s.filter.text, k, id)
    return t === null ? ok(s) : relocate({ ...s, filter: { active: true, text: t } }, 0)
  }
  if (!s.modal && s.screen === "settings" && s.settings?.editing != null) {
    if (id === "enter") return commitEdit(s)
    if (id === "escape") return ok({ ...s, settings: { ...s.settings, editing: null, error: null } })
    const t = textInput(s.settings.editing, k, id)
    return t === null ? ok(s) : ok({ ...s, settings: { ...s.settings, editing: t } })
  }
  for (const scope of scopes(s)) {
    const b = BINDINGS.find((x) => x.scope === scope && x.keys.includes(id))
    if (b) return b.run(s)
  }
  return ok(s)
}

export function footerHints(s: AppState): { left: string[]; right: string[] } {
  const hints = (scope: Scope) => BINDINGS.filter((b) => b.scope === scope && b.hint).map((b) => b.hint!)
  if (s.modal) return { left: hints(s.modal.kind), right: [] }
  if (s.screen === "queue" && s.filter.active) return { left: ["type to filter", "⏎ keep", "esc clear"], right: [] }
  if (s.screen === "settings" && s.settings?.editing != null) return { left: ["⏎ apply", "esc cancel"], right: [] }
  const right = s.screen === "settings" || s.screen === "fixes" ? [] : hints("daemon")
  return { left: [...hints(s.screen), ...hints("global")], right }
}
