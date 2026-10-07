// Single panel state and a pure reducer: update(state, action) → { state, cmds }.
// Commands (cmds) are executed by effects.ts; the reducer does no I/O.
import type { BridgeStatus } from "../bridge/client"
import type { BookDetail, FieldValue, Fix, FixCounts, FixesData, SettingsData, Snapshot } from "../bridge/types"
import { settleCursor } from "./fixes"
import { emptyHistory, pushSnapshot, type History } from "./history"
import { handleKey } from "./keys"
import { selectedName, visibleBooks } from "./select"

export type Screen = "queue" | "book" | "telemetry" | "settings" | "fixes"
export type FixFilter = "all" | "review" | "applied" | "reverted" | "not_found"
export type MathMode = "readable" | "raw"
export interface FixesView { book: string; data: FixesData | null; cursorId: string | null; filter: FixFilter; back: Screen
  error?: string | null; math?: MathMode }       // math: unset means "readable"
export interface DirEntry { name: string; dir: boolean }
export type ActName = "skip" | "retry" | "bump" | "run" | "daemon_start" | "daemon_toggle" | "daemon_stop"
export type Command =
  | { kind: "snapshot" }
  | { kind: "act"; action: ActName; books?: string[]; delta?: number }
  | { kind: "add"; paths: string[] }
  | { kind: "loadBook"; name: string }
  | { kind: "loadSettings" }
  | { kind: "saveSettings"; updates: { section: string; key: string; value: FieldValue }[] }
  | { kind: "editToml"; path: string }
  | { kind: "openFolder"; path: string }
  | { kind: "listDir"; dir: string; focus?: string }
  | { kind: "log"; lines: number }
  | { kind: "loadFixes"; book: string }
  | { kind: "fixSet"; book: string; id: string; applied: boolean }
  | { kind: "fixKeep"; book: string; id: string }
  | { kind: "notify"; text: string; level: "info" | "error" }
  | { kind: "quit" }
export type Modal =
  | null
  | { kind: "help" }
  | { kind: "confirm"; text: string; cmd: Command }
  | { kind: "add"; dir: string; entries: DirEntry[]; cursor: number; marked: string[] }
export interface KeyInput { name: string; ctrl: boolean; shift: boolean; meta: boolean; sequence: string }
export interface SettingsState {
  data: SettingsData; cursor: number; draft: Record<string, FieldValue>; editing: string | null; error: string | null
}
export interface AppState {
  screen: Screen; modal: Modal
  bridge: BridgeStatus; snap: Snapshot | null; stale: boolean; polling: boolean
  cursor: number; marks: string[]; filter: { active: boolean; text: string }
  bookName: string | null; book: BookDetail | null; bookPane: "stages" | "quality"
  settings: SettingsState | null
  fixes: FixesView | null
  log: string[]; logScroll: number
  history: History
  toast: { text: string; level: "info" | "error"; until: number } | null
  size: { width: number; height: number }
}
export type Action =
  | { type: "key"; key: KeyInput }
  | { type: "poll" }
  | { type: "slowTick"; now: number }
  | { type: "snapshot"; snap: Snapshot; now: number }
  | { type: "stale" }
  | { type: "bridge"; status: BridgeStatus }
  | { type: "bookLoaded"; detail: BookDetail }
  | { type: "settingsLoaded"; data: SettingsData }
  | { type: "dirListed"; dir: string; entries: DirEntry[]; focus?: string }
  | { type: "log"; lines: string[] }
  | { type: "fixesLoaded"; book: string; data: FixesData }
  | { type: "fixesFailed"; book: string; error: string }
  | { type: "fixUpdated"; book: string; fix: Fix; counts: FixCounts }
  | { type: "toast"; text: string; level: "info" | "error"; now: number }
  | { type: "resize"; width: number; height: number }
export interface Result { state: AppState; cmds: Command[] }

export const TOAST_MS = 4000
export const LOG_LINES = 200

// The screen draws fields by section (in order of first appearance): the cursor must follow the same order.
function groupBySection(data: SettingsData): SettingsData {
  const order: string[] = []
  for (const f of data.fields) if (!order.includes(f.section)) order.push(f.section)
  return { ...data, fields: order.flatMap((sec) => data.fields.filter((f) => f.section === sec)) }
}

export function initialState(width: number, height: number): AppState {
  return {
    screen: "queue", modal: null, bridge: { kind: "connecting" }, snap: null, stale: false, polling: false,
    cursor: 0, marks: [], filter: { active: false, text: "" },
    bookName: null, book: null, bookPane: "stages", settings: null, fixes: null, log: [], logScroll: 0,
    history: emptyHistory(), toast: null, size: { width, height },
  }
}

/** Cursor within the bounds of the visible list; if the selected book changed, load its card. */
export function syncSelection(s: AppState): Result {
  const n = visibleBooks(s).length
  const cursor = Math.max(0, Math.min(s.cursor, n - 1))
  const st = { ...s, cursor }
  const name = selectedName(st)
  if (name === s.bookName) return { state: st, cmds: [] }
  return { state: { ...st, bookName: name }, cmds: name ? [{ kind: "loadBook", name }] : [] }
}

/** Cursor follows the book bookName if it is visible; otherwise stays at fallback (clamped later). */
export function relocate(s: AppState, fallback: number = s.cursor): Result {
  const i = visibleBooks(s).findIndex((b) => b.name === s.bookName)
  return syncSelection({ ...s, cursor: i >= 0 ? i : fallback })
}

export function update(s: AppState, a: Action): Result {
  switch (a.type) {
    case "key":
      return handleKey(s, a.key)
    case "poll":
      return s.polling ? { state: s, cmds: [] } : { state: { ...s, polling: true }, cmds: [{ kind: "snapshot" }] }
    case "stale":
      return { state: { ...s, stale: true, polling: false }, cmds: [] }
    case "snapshot": {
      const names = new Set(a.snap.books.map((b) => b.name))
      return relocate({
        ...s, snap: a.snap, stale: false, polling: false,
        marks: s.marks.filter((m) => names.has(m)),
        history: pushSnapshot(s.history, a.snap, a.now),
      })
    }
    case "bridge":
      return { state: { ...s, bridge: a.status }, cmds: [] }
    case "bookLoaded":
      return { state: a.detail.info.name === s.bookName ? { ...s, book: a.detail } : s, cmds: [] }
    case "settingsLoaded":
      return { state: { ...s, settings: { data: groupBySection(a.data), cursor: s.settings?.cursor ?? 0, draft: {}, editing: null,
                                          error: null } }, cmds: [] }
    case "dirListed":
      if (s.modal?.kind !== "add") return { state: s, cmds: [] }
      const at = a.focus ? a.entries.findIndex((e) => e.name === a.focus) : -1   // "up": cursor on the folder we came from
      return { state: { ...s, modal: { kind: "add", dir: a.dir, entries: a.entries, cursor: Math.max(0, at), marked: s.modal.marked } }, cmds: [] }
    case "log":
      return { state: { ...s, log: a.lines }, cmds: [] }
    case "fixesLoaded":
      if (s.fixes?.book !== a.book) return { state: s, cmds: [] }
      return { state: { ...s, fixes: settleCursor({ ...s.fixes, data: a.data, error: null }) }, cmds: [] }
    case "fixesFailed":
      if (s.fixes?.book !== a.book) return { state: s, cmds: [] }
      return { state: { ...s, fixes: { ...s.fixes, error: a.error } }, cmds: [] }
    case "fixUpdated": {
      if (s.fixes?.book !== a.book || !s.fixes.data) return { state: s, cmds: [] }
      const fixes = s.fixes.data.fixes.map((f) => (f.id === a.fix.id ? a.fix : f))
      return { state: { ...s, fixes: settleCursor({ ...s.fixes, data: { ...s.fixes.data, fixes, counts: a.counts } }) }, cmds: [] }
    }
    case "toast":
      return { state: { ...s, toast: { text: a.text, level: a.level, until: a.now + TOAST_MS } }, cmds: [] }
    case "resize":
      return { state: { ...s, size: { width: a.width, height: a.height } }, cmds: [] }
    case "slowTick": {
      const cmds: Command[] = []
      if (s.bookName && (s.screen === "queue" || s.screen === "book" || s.screen === "telemetry"))
        cmds.push({ kind: "loadBook", name: s.bookName })
      if (s.screen === "telemetry") cmds.push({ kind: "log", lines: LOG_LINES })
      const toast = s.toast && a.now > s.toast.until ? null : s.toast
      return { state: { ...s, toast }, cmds }
    }
  }
}
