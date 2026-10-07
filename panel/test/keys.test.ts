import { describe, expect, test } from "bun:test"
import { footerHints, handleKey, keyId } from "../src/state/keys"
import { initialState, update, type AppState, type KeyInput } from "../src/state/store"
import { LIBRARY, snap } from "./fixtures/state"
import type { Fix, FixesData, SettingsData } from "../src/bridge/types"

const k = (sequence: string, name = sequence, mods: Partial<KeyInput> = {}): KeyInput =>
  ({ name, sequence, ctrl: false, shift: false, meta: false, ...mods })
const DOWN = k("\x1b[B", "down"), UP = k("\x1b[A", "up"), SPACE = k(" ", "space"), ENTER = k("\r", "return")
const ESC = k("\x1b", "escape"), BKSP = k("\x7f", "backspace")

function loaded(): AppState {
  return update(initialState(120, 35), { type: "snapshot", snap: snap(LIBRARY), now: 0 }).state
}
function press(s: AppState, ...keys: KeyInput[]) {
  let cmds: any[] = []
  for (const key of keys) { const r = update(s, { type: "key", key }); s = r.state; cmds = cmds.concat(r.cmds) }
  return { s, cmds }
}

test("keyId normalizes printable chars and named keys", () => {
  expect(keyId(k("?", "/", { shift: true }))).toBe("?")
  expect(keyId(k("+"))).toBe("+")
  expect(keyId(ENTER)).toBe("enter")
  expect(keyId(SPACE)).toBe("space")
  expect(keyId(k("\x13", "s", { ctrl: true }))).toBe("ctrl+s")
})

describe("queue", () => {
  test("move, mark, run marked", () => {
    let { s } = press(loaded(), DOWN, SPACE, SPACE)          // ␣ marks and moves the cursor down
    expect(s.marks).toEqual([LIBRARY[1].name, LIBRARY[2].name])
    const r = press(s, k("x"))
    expect(r.cmds).toContainEqual({ kind: "act", action: "run", books: [LIBRARY[1].name, LIBRARY[2].name] })
    expect(r.s.marks).toEqual([])                             // run clears the marks
  })
  test("action without marks targets the cursor row", () => {
    const { cmds } = press(loaded(), DOWN, k("s"))
    expect(cmds).toContainEqual({ kind: "act", action: "skip", books: [LIBRARY[1].name] })
  })
  test("priority bump and cursor clamps", () => {
    const { s, cmds } = press(loaded(), UP, UP, k("+"), k("-"))
    expect(s.cursor).toBe(0)
    expect(cmds).toContainEqual({ kind: "act", action: "bump", books: [LIBRARY[0].name], delta: 1 })
    expect(cmds).toContainEqual({ kind: "act", action: "bump", books: [LIBRARY[0].name], delta: -1 })
  })
  test("filter by substring, escape clears", () => {
    let { s } = press(loaded(), k("/"), k("С"), k("а"), k("ф"))
    expect(s.filter).toEqual({ active: true, text: "Саф" })
    ;({ s } = press(s, ENTER))
    expect(s.filter.active).toBe(false)
    ;({ s } = press(s, k("j")))                          // after Enter, j is movement again, not input
    expect(s.filter.text).toBe("Саф")
    ;({ s } = press(s, k("/"), BKSP, BKSP, BKSP, ESC))
    expect(s.filter).toEqual({ active: false, text: "" })
  })
  test("enter opens book screen and loads detail", () => {
    const { s, cmds } = press(loaded(), ENTER)
    expect(s.screen).toBe("book")
    expect(cmds).toContainEqual({ kind: "loadBook", name: LIBRARY[0].name })
  })
  test("stop asks for confirmation", () => {
    let { s, cmds } = press(loaded(), k("t"))
    expect(s.modal?.kind).toBe("confirm")
    expect(cmds).toEqual([])
    ;({ s, cmds } = press(s, k("y")))
    expect(s.modal).toBe(null)
    expect(cmds).toContainEqual({ kind: "act", action: "daemon_stop" })
  })
  test("footer hints for queue", () => {
    const h = footerHints(loaded())
    expect(h.left).toContain("␣ mark")
    expect(h.right).toEqual(["d start", "p pause", "t stop"])
  })
})

test("q quits from any screen, digits switch screens", () => {
  let { s, cmds } = press(loaded(), k("3"))
  expect(s.screen).toBe("telemetry")
  expect(cmds).toContainEqual({ kind: "log", lines: 200 })
  ;({ s, cmds } = press(s, k("4")))
  expect(s.screen).toBe("settings")
  expect(cmds).toContainEqual({ kind: "loadSettings" })
  ;({ cmds } = press(s, k("q")))
  expect(cmds).toContainEqual({ kind: "quit" })
})

test("help modal opens and closes", () => {
  let { s } = press(loaded(), k("?"))
  expect(s.modal?.kind).toBe("help")
  ;({ s } = press(s, k("j"), ESC))
  expect(s.modal).toBe(null)
  expect(s.cursor).toBe(0)                               // j inside help did not move the queue
})

const CTRLC = k("\x03", "c", { ctrl: true })
const FIELDS = [
  { section: "pipeline", key: "workers", kind: "int" as const, choices: [], value: 2, comment: null },
  { section: "pipeline", key: "mode", kind: "choice" as const, choices: ["fast", "cascade"], value: "fast", comment: null },
]
const withSettings = (s: AppState, over: Partial<NonNullable<AppState["settings"]>> = {}): AppState =>
  ({ ...s, screen: "settings", settings: { data: { path: "/x/techbookocr.toml", fields: FIELDS }, cursor: 0, draft: {}, editing: null, error: null, ...over } })

describe("ctrl+c quits everywhere", () => {
  const quit = { kind: "quit" }
  test("filter input", () => expect(press(loaded(), k("/"), CTRLC).cmds).toContainEqual(quit))
  test("settings edit", () =>
    expect(press(withSettings(loaded(), { editing: "3" }), CTRLC).cmds).toContainEqual(quit))
  test("confirm modal", () => expect(press(loaded(), k("t"), CTRLC).cmds).toContainEqual(quit))
  test("add modal", () => expect(press(loaded(), k("a"), CTRLC).cmds).toContainEqual(quit))
  test("help modal", () => expect(press(loaded(), k("?"), CTRLC).cmds).toContainEqual(quit))
})

describe("russian layout", () => {
  test("й quits, о/л move", () => {
    expect(press(loaded(), k("й")).cmds).toContainEqual({ kind: "quit" })
    expect(press(loaded(), k("о")).s.cursor).toBe(1)
    expect(press(loaded(), k("о"), k("л")).s.cursor).toBe(0)
  })
  test("uppercase maps too", () => expect(press(loaded(), k("Й")).cmds).toContainEqual({ kind: "quit" }))
  test("filter keeps literal cyrillic", () =>
    expect(press(loaded(), k("/"), k("й")).s.filter.text).toBe("й"))
})

test("actions never hit rows hidden by the filter", () => {
  let { s } = press(loaded(), SPACE)                         // book 0 is marked
  s = { ...s, filter: { active: false, text: "Саф" }, cursor: 0 }
  const { cmds } = press(s, k("s"))
  expect(cmds).toContainEqual({ kind: "act", action: "skip", books: [LIBRARY[1].name] })
})

describe("settings screen reload", () => {
  test("4 with a draft does not reload", () => {
    const s = withSettings(loaded(), { draft: { "pipeline.workers": 3 } })
    const r = press(s, k("4"))
    expect(r.cmds).toEqual([])
    expect(r.s.settings?.draft).toEqual({ "pipeline.workers": 3 })
  })
  test("4 on settings never reloads", () =>
    expect(press(withSettings(loaded()), k("4")).cmds).toEqual([]))
})

test("pasted text loses control characters", () => {
  const { s } = press(loaded(), k("/"), k("ab\ncd", "paste"))
  expect(s.filter.text).toBe("abcd")
})

const SETTINGS: SettingsData = {
  path: "/repo/techbookocr.toml",
  fields: [
    { section: "pipeline", key: "mode", kind: "choice", choices: ["fast", "cascade"], value: "fast", comment: "режим" },
    { section: "pipeline", key: "webp_quality", kind: "int", choices: [], value: 70, comment: null },
    { section: "library", key: "auto_summarize", kind: "bool", choices: [], value: true, comment: null },
  ],
}

test("settings: cycle choice, edit int, save, discard", () => {
  let s = update(loaded(), { type: "settingsLoaded", data: SETTINGS }).state
  s = { ...s, screen: "settings" }
  let r = press(s, k("\x1b[C", "right"))
  expect(r.s.settings!.draft).toEqual({ "pipeline.mode": "cascade" })
  r = press(r.s, DOWN, ENTER, BKSP, BKSP, k("8"), k("5"), ENTER)
  expect(r.s.settings!.draft["pipeline.webp_quality"]).toBe(85)
  r = press(r.s, ENTER, BKSP, BKSP, k("x"), ENTER)
  expect(r.s.settings!.error).toBe("webp_quality: not an integer")
  r = press(r.s, ESC, k("\x13", "s", { ctrl: true }))
  expect(r.cmds).toContainEqual({ kind: "saveSettings", updates: [
    { section: "pipeline", key: "mode", value: "cascade" },
    { section: "pipeline", key: "webp_quality", value: 85 }] })
  r = press(r.s, ESC)
  expect(r.s.settings!.draft).toEqual({})
  r = press(r.s, DOWN, DOWN, k("\x1b[C", "right"))
  expect(r.s.settings!.draft).toEqual({ "library.auto_summarize": false })
})

test("add books modal: navigate, mark, add", () => {
  let { s, cmds } = press(loaded(), k("a"))
  expect(s.modal?.kind).toBe("add")
  expect(cmds[0]).toMatchObject({ kind: "listDir" })
  s = update(s, { type: "dirListed", dir: "/books", entries: [
    { name: "sub", dir: true }, { name: "a.djvu", dir: false }, { name: "b.pdf", dir: false }] }).state
  ;({ cmds } = press(s, ENTER))
  expect(cmds).toContainEqual({ kind: "listDir", dir: "/books/sub" })
  ;({ s, cmds } = press(s, DOWN, SPACE, SPACE, ENTER))
  expect(cmds).toContainEqual({ kind: "add", paths: ["/books/a.djvu", "/books/b.pdf"] })
  expect(s.modal).toBe(null)
  ;({ s } = press(loaded(), k("a")))
  s = update(s, { type: "dirListed", dir: "/books", entries: [] }).state
  ;({ cmds } = press(s, BKSP))
  expect(cmds).toContainEqual({ kind: "listDir", dir: "/", focus: "books" })
})

test("add books: marks survive folder navigation", () => {
  let { s } = press(loaded(), k("a"))
  s = update(s, { type: "dirListed", dir: "/a", entries: [{ name: "x.pdf", dir: false }] }).state
  ;({ s } = press(s, SPACE))
  s = update(s, { type: "dirListed", dir: "/b", entries: [{ name: "y.djvu", dir: false }] }).state
  expect(s.modal).toMatchObject({ dir: "/b", cursor: 0, marked: ["/a/x.pdf"] })
  ;({ s } = press(s, SPACE))
  s = update(s, { type: "dirListed", dir: "/b", entries: [{ name: "y.djvu", dir: false }] }).state
  const { cmds } = press(s, ENTER)
  expect(cmds).toContainEqual({ kind: "add", paths: ["/a/x.pdf", "/b/y.djvu"] })
})

test("add books: Space marks a folder, Enter on a file adds folders and files together", () => {
  let { s } = press(loaded(), k("a"))
  s = update(s, { type: "dirListed", dir: "/books", entries: [
    { name: "sub", dir: true }, { name: "a.djvu", dir: false }] }).state
  ;({ s } = press(s, SPACE))                                   // marked the folder, cursor on a.djvu
  expect(s.modal).toMatchObject({ marked: ["/books/sub"], cursor: 1 })
  const { cmds } = press(s, ENTER)
  expect(cmds).toContainEqual({ kind: "add", paths: ["/books/sub"] })
})

test("add books: Enter on a folder still opens it even when marked", () => {
  let { s } = press(loaded(), k("a"))
  s = update(s, { type: "dirListed", dir: "/books", entries: [{ name: "sub", dir: true }] }).state
  ;({ s } = press(s, SPACE))
  s = update(s, { type: "dirListed", dir: "/books", entries: [{ name: "sub", dir: true }] }).state
  const { cmds } = press(s, ENTER)
  expect(cmds).toEqual([{ kind: "listDir", dir: "/books/sub" }])
})

test("add books: going up puts the cursor on the folder we came from", () => {
  let { s } = press(loaded(), k("a"))
  const entries = [{ name: "a", dir: true }, { name: "books", dir: true }, { name: "z", dir: true }]
  s = update(s, { type: "dirListed", dir: "/books", entries: [] }).state
  s = update(s, { type: "dirListed", dir: "/", entries, focus: "books" }).state
  expect(s.modal).toMatchObject({ dir: "/", cursor: 1 })
  s = update(s, { type: "dirListed", dir: "/x", entries, focus: "missing" }).state
  expect(s.modal).toMatchObject({ cursor: 0 })
})

test("add books: `a` adds the marked folders even with the cursor on a folder", () => {
  let { s } = press(loaded(), k("a"))
  const entries = [{ name: "p", dir: true }, { name: "q", dir: true }]
  s = update(s, { type: "dirListed", dir: "/books", entries }).state
  ;({ s } = press(s, SPACE))                                   // p is marked, cursor on q (folder)
  const { s: after, cmds } = press(s, k("a"))
  expect(cmds).toEqual([{ kind: "add", paths: ["/books/p"] }])
  expect(after.modal).toBe(null)
})

test("add books: `a` without marks on a folder asks, then adds that folder", () => {
  let { s } = press(loaded(), k("a"))
  s = update(s, { type: "dirListed", dir: "/books", entries: [{ name: "p", dir: true }] }).state
  const r = press(s, k("a"), k("y"))
  expect(r.cmds).toEqual([{ kind: "add", paths: ["/books/p"] }])
})

describe("unsaved settings draft", () => {
  const DRAFT = { "pipeline.mode": "cascade" }
  test("survives leaving Settings and coming back (no reload)", () => {
    let { s } = press(withSettings(loaded(), { draft: DRAFT }), k("1"))
    expect(s.screen).toBe("queue")
    const r = press(s, k("4"))
    expect(r.cmds).toEqual([])
    expect(r.s.screen).toBe("settings")
    expect(r.s.settings?.draft).toEqual(DRAFT)
  })
  test("without a draft re-entry still reloads", () => {
    const { s } = press(withSettings(loaded()), k("1"))
    expect(press(s, k("4")).cmds).toEqual([{ kind: "loadSettings" }])
  })
  test("q asks before discarding, y quits, n stays", () => {
    const r = press(withSettings(loaded(), { draft: DRAFT }), k("q"))
    expect(r.cmds).toEqual([])
    expect(r.s.modal).toMatchObject({ kind: "confirm", text: "Discard unsaved settings and quit?" })
    expect(press(r.s, k("y")).cmds).toEqual([{ kind: "quit" }])
    const n = press(r.s, k("n"))
    expect(n.cmds).toEqual([])
    expect(n.s.modal).toBe(null)
    expect(n.s.settings?.draft).toEqual(DRAFT)
  })
  test("draft is respected on other screens too; ctrl+c asks once, twice quits", () => {
    const base = { ...withSettings(loaded(), { draft: DRAFT }), screen: "queue" as const }
    const r = press(base, CTRLC)
    expect(r.cmds).toEqual([])
    expect(r.s.modal?.kind).toBe("confirm")
    expect(press(r.s, CTRLC).cmds).toEqual([{ kind: "quit" }])
  })
  test("q without a draft quits at once", () => {
    expect(press(withSettings(loaded()), k("q")).cmds).toEqual([{ kind: "quit" }])
  })
})

describe("add books: folder under the cursor needs confirmation", () => {
  const open = () => {
    let { s } = press(loaded(), k("a"))
    return update(s, { type: "dirListed", dir: "/home/u", entries: [
      { name: "lib", dir: true }, { name: "a.djvu", dir: false }] }).state
  }
  test("a on an unmarked folder asks first; y adds, n cancels", () => {
    const r = press(open(), k("a"))
    expect(r.cmds).toEqual([])
    expect(r.s.modal).toMatchObject({ kind: "confirm", text: "Add every .djvu/.pdf under /home/u/lib (recursive)?",
                                      cmd: { kind: "add", paths: ["/home/u/lib"] } })
    expect(press(r.s, k("y")).cmds).toEqual([{ kind: "add", paths: ["/home/u/lib"] }])
    expect(press(r.s, k("n")).cmds).toEqual([])
  })
  test("a on a file and a on marked items add without confirmation", () => {
    expect(press(open(), DOWN, k("a")).cmds).toEqual([{ kind: "add", paths: ["/home/u/a.djvu"] }])
    const marked = press(open(), SPACE, k("a"))                 // a folder is marked: a deliberate choice
    expect(marked.cmds).toEqual([{ kind: "add", paths: ["/home/u/lib"] }])
  })
})

const fix = (id: string, state: Fix["state"], suggested = false): Fix => ({
  id, scan: id.split("-")[0], page: null, block: null, kind: null, was: "a", now: "b", state, suggested,
  reason: null, decided_by: "model", before: "", after: "" })
const FDATA: FixesData = { fixes: [fix("0007-1", "reverted"), fix("0046-1", "applied", true), fix("0106-1", "not_found")],
  counts: { applied: 0, reverted: 1, suggested: 1, not_found: 1 }, editable: true, why_not: null }

describe("fixes", () => {
  function opened(data: FixesData = FDATA) {
    const { s, cmds } = press(loaded(), k("f"))
    expect(cmds).toContainEqual({ kind: "loadFixes", book: s.bookName })
    expect(s.screen).toBe("fixes")
    return update(s, { type: "fixesLoaded", book: s.bookName!, data }).state
  }
  test("f opens Fixes for the selected book; Esc returns", () => {
    const s = opened()
    expect(press(s, ESC).s.screen).toBe("queue")
    const fromBook = press(update(loaded(), { type: "key", key: ENTER }).state, k("f")).s
    expect(press(update(fromBook, { type: "fixesLoaded", book: fromBook.bookName!, data: FDATA }).state, ESC).s.screen).toBe("book")
  })
  test("space toggles, enter keeps, n jumps to review, / cycles filter", () => {
    let s = opened()
    let r = press(s, SPACE)                                               // 0007-1 reverted → apply
    expect(r.cmds).toEqual([{ kind: "fixSet", book: s.bookName, id: "0007-1", applied: true }])
    r = press(s, k("n"))
    expect(r.s.fixes!.cursorId).toBe("0046-1")
    expect(press(r.s, SPACE).cmds).toEqual([{ kind: "fixSet", book: s.bookName, id: "0046-1", applied: false }])
    expect(press(r.s, ENTER).cmds).toEqual([{ kind: "fixKeep", book: s.bookName, id: "0046-1" }])
    r = press(r.s, DOWN)
    expect(r.s.fixes!.cursorId).toBe("0106-1")
    expect(press(r.s, SPACE).cmds[0]).toMatchObject({ kind: "notify", level: "error" })    // not_found
    r = press(s, k("/"))
    expect(r.s.fixes!.filter).toBe("review")
    expect(r.s.fixes!.cursorId).toBe("0046-1")
  })
  test("m toggles readable / raw math; default is readable", () => {
    const s = opened()
    expect(s.fixes!.math).toBe("readable")
    const raw = press(s, k("m"))
    expect(raw.s.fixes!.math).toBe("raw")
    expect(raw.cmds).toEqual([])
    expect(press(raw.s, k("m")).s.fixes!.math).toBe("readable")
    expect(footerHints(s).left).toContain("m math")
    expect(press(raw.s, k("/")).s.fixes!.math).toBe("raw")                 // the filter keeps the mode
  })
  test("read-only: space and enter only notify", () => {
    const s = opened({ ...FDATA, editable: false, why_not: "book is processing" })
    expect(press(s, SPACE).cmds).toEqual([{ kind: "notify", text: "read-only: book is processing", level: "error" }])
    expect(press(s, ENTER).cmds[0]).toMatchObject({ kind: "notify" })
  })
  test("footer shows fixes hints without daemon keys", () => {
    const f = footerHints(opened())
    expect(f.left).toContain("␣ toggle")
    expect(f.right).toEqual([])
  })
  test("daemon keys are not active on the fixes screen", () => {
    const s = opened()
    expect(press(s, k("d")).cmds).toEqual([])
    expect(press(s, k("p")).cmds).toEqual([])
  })
  test("space or enter on a ? fix steps the cursor to the next ? fix", () => {
    const more: FixesData = { ...FDATA, fixes: [fix("0007-1", "reverted"), fix("0046-1", "applied", true), fix("0075-1", "applied"),
      fix("0130-1", "applied", true)] }
    const s = opened(more)
    const at = (id: string) => ({ ...s, fixes: { ...s.fixes!, cursorId: id } })
    let r = press(at("0046-1"), SPACE)
    expect(r.cmds).toEqual([{ kind: "fixSet", book: s.bookName, id: "0046-1", applied: false }])
    expect(r.s.fixes!.cursorId).toBe("0130-1")
    r = press(at("0046-1"), ENTER)
    expect(r.cmds).toEqual([{ kind: "fixKeep", book: s.bookName, id: "0046-1" }])
    expect(r.s.fixes!.cursorId).toBe("0130-1")
    r = press(at("0130-1"), SPACE)                                        // wraps around
    expect(r.s.fixes!.cursorId).toBe("0046-1")
    r = press(at("0075-1"), SPACE)                                        // not a "?": the cursor stays
    expect(r.cmds[0]).toMatchObject({ kind: "fixSet" })
    expect(r.s.fixes!.cursorId).toBe("0075-1")
  })
  test("v opens the scan fragment of the current fix; without one it only notifies", () => {
    const withCrop: FixesData = { ...FDATA, out_dir: "/lib/a",
      fixes: [{ ...fix("0007-1", "reverted"), crop: "fixes/0007-b2.webp" }, fix("0046-1", "applied", true)] }
    const s = opened(withCrop)
    expect(press(s, k("v")).cmds).toEqual([{ kind: "openFile", path: "/lib/a/fixes/0007-b2.webp" }])
    expect(press(s, DOWN, k("v")).cmds).toEqual([
      { kind: "notify", text: "no scan fragment (book assembled before this feature)", level: "info" }])
    const ro = opened({ ...withCrop, editable: false, why_not: "book is processing" })
    expect(press(ro, k("v")).cmds[0]).toMatchObject({ kind: "openFile" })            // viewing works while processing too
    expect(footerHints(s).left).toContain("v scan")
  })
  test("v without out_dir in the reply falls back to the open book's folder", () => {
    const s = opened({ ...FDATA, fixes: [{ ...fix("0007-1", "reverted"), crop: "fixes/0007-b2.webp" }] })
    const withBook = { ...s, book: { ...(s.book ?? {}), info: { name: s.fixes!.book }, out_dir: "/out/b" } as never }
    expect(press(withBook, k("v")).cmds).toEqual([{ kind: "openFile", path: "/out/b/fixes/0007-b2.webp" }])
    expect(press(s, k("v")).cmds[0]).toMatchObject({ kind: "notify", level: "error" })
  })
  test("the only ? fix: the cursor stays; read-only does not move it", () => {
    const s = press(opened(), k("n")).s
    expect(press(s, SPACE).s.fixes!.cursorId).toBe("0046-1")
    expect(press(s, ENTER).s.fixes!.cursorId).toBe("0046-1")
    const ro = press(opened({ ...FDATA, editable: false, why_not: "x" }), k("n")).s
    expect(press(ro, SPACE).s.fixes!.cursorId).toBe("0046-1")
  })
})
