import { expect, test } from "bun:test"
import { initialState, TOAST_MS, update, type AppState } from "../src/state/store"
import { DETAIL, LIBRARY, book, snap } from "./fixtures/state"
import type { Fix, FixesData } from "../src/bridge/types"
import { nextReview, settleCursor, visibleFixes } from "../src/state/fixes"

const s0 = () => update(initialState(120, 35), { type: "snapshot", snap: snap(LIBRARY), now: 0 }).state

test("first snapshot selects first book and loads its card", () => {
  const r = update(initialState(120, 35), { type: "snapshot", snap: snap(LIBRARY), now: 0 })
  expect(r.state.bookName).toBe(LIBRARY[0].name)
  expect(r.cmds).toContainEqual({ kind: "loadBook", name: LIBRARY[0].name })
  expect(r.state.polling).toBe(false)
})

test("marks survive refresh, vanished book loses its mark, cursor clamps", () => {
  let s = s0()
  s = { ...s, marks: [LIBRARY[3].name, LIBRARY[1].name], cursor: 3, bookName: LIBRARY[3].name }
  s = update(s, { type: "snapshot", snap: snap(LIBRARY.slice(0, 2)), now: 1 }).state
  expect(s.marks).toEqual([LIBRARY[1].name])
  expect(s.cursor).toBe(1)
})

test("reordered snapshot keeps the cursor on the same book", () => {
  const s = { ...s0(), cursor: 1, bookName: LIBRARY[1].name }
  const r = update(s, { type: "snapshot", snap: snap([LIBRARY[3], LIBRARY[2], LIBRARY[1], LIBRARY[0]]), now: 1 })
  expect(r.state.bookName).toBe(LIBRARY[1].name)
  expect(r.state.cursor).toBe(2)
  expect(r.cmds).toEqual([])
})

test("poll is not doubled while in flight", () => {
  let r = update(s0(), { type: "poll" })
  expect(r.cmds).toEqual([{ kind: "snapshot" }])
  r = update(r.state, { type: "poll" })
  expect(r.cmds).toEqual([])
  r = update(r.state, { type: "stale" })
  expect(r.state.stale).toBe(true)
  expect(r.state.polling).toBe(false)
})

test("book detail only for the current bookName", () => {
  let s = update(s0(), { type: "bookLoaded", detail: DETAIL }).state
  expect(s.book?.info.name).toBe(LIBRARY[0].name)
  s = update(s, { type: "bookLoaded", detail: { ...DETAIL, info: { ...DETAIL.info, name: "other" } } }).state
  expect(s.book?.info.name).toBe(LIBRARY[0].name)
})

test("toast expires on slow tick; slow tick reloads card and log", () => {
  let s = update(s0(), { type: "toast", text: "hi", level: "info", now: 0 }).state
  expect(s.toast?.text).toBe("hi")
  let r = update({ ...s, screen: "telemetry" }, { type: "slowTick", now: TOAST_MS + 1 })
  expect(r.state.toast).toBe(null)
  expect(r.cmds).toContainEqual({ kind: "loadBook", name: LIBRARY[0].name })
  expect(r.cmds).toContainEqual({ kind: "log", lines: 200 })
})

test("empty queue snapshot", () => {
  const s = update(initialState(120, 35), { type: "snapshot", snap: snap([]), now: 0 }).state
  expect(s.bookName).toBe(null)
  expect(s.cursor).toBe(0)
})

test("filter hides rows and keeps cursor in range", () => {
  let s = { ...s0(), filter: { active: false, text: "asm" }, cursor: 3 }
  s = update(s, { type: "snapshot", snap: snap([...LIBRARY, book("asm-2")]), now: 2 }).state
  expect(s.cursor).toBe(1)
})

test("settingsLoaded orders fields by section as drawn, so the cursor walks top to bottom", () => {
  const f = (section: string, key: string) => ({ section, key, kind: "int" as const, choices: [], value: 1, comment: null })
  const data = { path: "/x.toml", fields: [f("pipeline", "mode"), f("library", "dir"), f("render", "min_dpi"),
                                          f("pipeline", "webp_quality"), f("library", "idle_poll_s")] }
  const s = update(s0(), { type: "settingsLoaded", data }).state
  expect(s.settings!.data.fields.map((x) => `${x.section}.${x.key}`)).toEqual(
    ["pipeline.mode", "pipeline.webp_quality", "library.dir", "library.idle_poll_s", "render.min_dpi"])
})

const fx = (id: string, state: Fix["state"], suggested = false): Fix => ({
  id, scan: id.split("-")[0], page: null, block: null, kind: null, was: "a", now: "b", state, suggested,
  reason: null, decided_by: "model", before: "", after: "" })
const DATA: FixesData = { fixes: [fx("0007-1", "reverted"), fx("0046-1", "applied", true), fx("0075-1", "applied"),
  fx("0106-1", "not_found"), fx("0130-1", "applied", true)], counts: { applied: 1, reverted: 1, suggested: 2, not_found: 1 },
  editable: true, why_not: null }

test("fixes: loaded data keeps the cursor on the same id; filters and next review", () => {
  let s: AppState = { ...initialState(120, 35), screen: "fixes",
            fixes: { book: "b", data: null, cursorId: null, filter: "all" as const, back: "book" as const } }
  s = update(s, { type: "fixesLoaded", book: "b", data: DATA }).state
  expect(s.fixes!.cursorId).toBe("0007-1")
  s = { ...s, fixes: { ...s.fixes!, cursorId: "0075-1" } }
  s = update(s, { type: "fixesLoaded", book: "b", data: DATA }).state
  expect(s.fixes!.cursorId).toBe("0075-1")
  expect(visibleFixes({ ...s.fixes!, filter: "review" }).map((f) => f.id)).toEqual(["0046-1", "0130-1"])
  expect(settleCursor({ ...s.fixes!, filter: "review" }).cursorId).toBe("0046-1")
  expect(nextReview({ ...s.fixes!, cursorId: "0046-1" })).toBe("0130-1")
  expect(nextReview({ ...s.fixes!, cursorId: "0130-1" })).toBe("0046-1")      // wraps around
  const upd = update(s, { type: "fixUpdated", book: "b", fix: { ...fx("0075-1", "reverted") },
                          counts: { applied: 0, reverted: 2, suggested: 2, not_found: 1 } }).state
  expect(upd.fixes!.data!.fixes.find((f) => f.id === "0075-1")!.state).toBe("reverted")
  expect(upd.fixes!.data!.counts.reverted).toBe(2)
  const other = update(s, { type: "fixesLoaded", book: "zzz", data: DATA }).state
  expect(other).toBe(s)                                                        // a reply for another book is not applied
})

test("fixesFailed stores the error for the open book; fixesLoaded clears it", () => {
  let s: AppState = { ...initialState(120, 35), screen: "fixes",
            fixes: { book: "b", data: null, cursorId: null, filter: "all" as const, back: "book" as const } }
  s = update(s, { type: "fixesFailed", book: "b", error: "bridge timeout" }).state
  expect(s.fixes!.error).toBe("bridge timeout")
  expect(s.fixes!.data).toBeNull()
  expect(update(s, { type: "fixesFailed", book: "zzz", error: "x" }).state).toBe(s)    // another book
  s = update(s, { type: "fixesLoaded", book: "b", data: DATA }).state
  expect(s.fixes!.error).toBeNull()
})
