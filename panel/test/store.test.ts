import { expect, test } from "bun:test"
import { initialState, TOAST_MS, update } from "../src/state/store"
import { DETAIL, LIBRARY, book, snap } from "./fixtures/state"

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
