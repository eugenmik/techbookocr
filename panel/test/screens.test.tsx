import { afterEach, expect, test } from "bun:test"
import { testRender } from "@opentui/solid"
import { StatusStrip } from "../src/components/StatusStrip"
import { ModalView } from "../src/screens/Modals"
import { BookScreen } from "../src/screens/Book"
import { Shell } from "../src/components/Shell"
import { SettingsScreen } from "../src/screens/Settings"
import { QueueScreen, bookRowText, windowTop } from "../src/screens/Queue"
import { createSignal } from "solid-js"
import { TextAttributes } from "@opentui/core"
import { initialState, update, type AppState } from "../src/state/store"
import { makeTheme } from "../src/theme"
import { strWidth } from "../src/format"
import { DETAIL, LIBRARY, book, snap } from "./fixtures/state"

let setup: Awaited<ReturnType<typeof testRender>> | null = null
afterEach(() => { setup?.renderer.destroy(); setup = null })

function stateWith(books = LIBRARY, w = 120, h = 35): AppState {
  let s = update(initialState(w, h), { type: "snapshot", snap: snap(books), now: 0 }).state
  return update(s, { type: "bookLoaded", detail: DETAIL }).state
}

/** `until` is the text to wait for (polling up to 2 s): <markdown> parses text asynchronously. */
async function frame(el: () => any, w = 120, h = 30, until?: string) {
  setup = await testRender(el, { width: w, height: h })
  await setup.renderOnce()
  let f = setup.captureCharFrame()
  const t0 = Date.now()
  while (until && !f.includes(until) && Date.now() - t0 < 2000) {
    await new Promise((r) => setTimeout(r, 20))
    await setup.renderOnce()
    f = setup.captureCharFrame()
  }
  return f
}

test("row text: status icon + word, progress, priority, error", () => {
  const p = bookRowText(LIBRARY[0], 30, true, false)
  expect(p.ptr).toBe("❯ ")
  expect(p.state.trim()).toBe("▸ arbiter")
  expect(p.detail.trim()).toBe("███████░░░  73%")
  expect(bookRowText(LIBRARY[1], 30, false, true).prio.trim()).toBe("p5")
  expect(bookRowText(LIBRARY[1], 30, false, true).ptr).toBe(" ●")
  expect(bookRowText(LIBRARY[3], 30, false, false).detail.trim()).toStartWith("StageAborted")
  expect(bookRowText(LIBRARY[2], 30, false, false).state.trim()).toBe("✓ done")
})

test("long and odd names keep columns aligned", () => {
  const odd = book("Очень?#длинное имя книги ".repeat(8) + "短い本", { scans: 10 })
  const p = bookRowText(odd, 30, false, false)
  expect(strWidth(p.name)).toBe(30)
  expect(p.name.endsWith("…")).toBe(true)
})

test("queue at 120×30: table, card, events", async () => {
  const f = await frame(() => <QueueScreen state={stateWith(LIBRARY, 120, 30)} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("Books  4")
  expect(f).toContain("❯")
  expect(f).toContain("Гиршович_Справочник")
  expect(f).toContain("✗ failed")
  expect(f).toContain("Recent events")
  expect(f).toContain("Stage")                  // card on the right
  expect(f).toContain("ETA 1h09m")
  expect(f).toMatchSnapshot()
})

test("queue at 80×24: card hidden", async () => {
  const f = await frame(() => <QueueScreen state={stateWith(LIBRARY, 80, 24)} theme={makeTheme({})} />, 78, 17)
  expect(f).not.toContain("ETA 1h09m")
  expect(f).toContain("Гиршович")
  expect(f).toMatchSnapshot()
})

test("NO_COLOR: no palette, status still readable by icon and word", async () => {
  const theme = makeTheme({ NO_COLOR: "1" })
  expect(theme.color).toBe(false)
  expect(theme.accent).toBeUndefined()
  const f = await frame(() => <QueueScreen state={stateWith(LIBRARY, 120, 30)} theme={theme} />, 118, 23)
  expect(f).toContain("▸ arbiter")
  expect(f).toContain("✓ done")
  expect(f).toContain("✗ failed")
})

test("empty queue state", async () => {
  const f = await frame(() => <QueueScreen state={stateWith([], 120, 30)} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("No books yet · press a to add")
})

test("marks and filter in the title", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30), marks: [LIBRARY[1].name], filter: { active: true, text: "С" } }
  const f = await frame(() => <QueueScreen state={s} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("1 marked")
  expect(f).toContain('filter "С"')
})

test("multi-line error and event message stay on one row", async () => {
  const books = [book("alpha", { status: "failed", error: "Boom:\n  at x\n  at y" }), book("beta"), book("gamma")]
  const s0 = stateWith(books, 120, 30)
  const s = { ...s0, snap: { ...s0.snap!, events: [{ ts: "2026-10-04T23:55:09", book: "alpha", level: "error", message: "line1\nline2" }] } }
  const f = await frame(() => <QueueScreen state={s} theme={makeTheme({})} />, 118, 23)
  const lines = f.trimEnd().split("\n")
  const i = lines.findIndex((l) => l.includes("alpha  "))
  expect(lines[i]).toContain("Boom: at x")
  expect(lines[i + 1]).toContain("beta")
  expect(lines[i + 2]).toContain("gamma")
  expect(f).toContain("line1 line2")
  expect(strWidth(bookRowText(books[0], 30, false, false).detail)).toBe(18)
})

test("selected row is reversed, others not", async () => {
  setup = await testRender(() => <QueueScreen state={stateWith(LIBRARY, 120, 30)} theme={makeTheme({})} />, { width: 118, height: 23 })
  await setup.renderOnce()
  const lines = setup.captureSpans().lines
  const rowOf = (name: string) => lines.find((l) => l.spans.map((x) => x.text).join("").includes(name))!
  const sel = rowOf("▸ arbiter").spans.filter((x) => /Гиршович|arbiter|73%/.test(x.text))
  expect(sel.length).toBeGreaterThan(0)
  expect(sel.every((x) => x.attributes & TextAttributes.INVERSE)).toBe(true)
  expect(rowOf("Сафронов").spans.some((x) => x.attributes & TextAttributes.INVERSE)).toBe(false)
})

test("windowTop: moves only when cursor leaves window", () => {
  const n = 30, h = 5
  expect(windowTop(0, 0, h, n)).toBe(0)
  expect(windowTop(0, h - 1, h, n)).toBe(0)
  expect(windowTop(0, h, h, n)).toBe(1)
  expect(windowTop(1, h - 1, h, n)).toBe(1)   // ↑ inside window: no scroll
  expect(windowTop(1, 0, h, n)).toBe(0)
  expect(windowTop(0, n - 1, h, n)).toBe(n - h)
  expect(windowTop(40, 3, h, 8)).toBe(3)      // clamp to [0, n-h]
})

test("scroll keeps last book visible and ↑ moves cursor within window", async () => {
  const many = Array.from({ length: 30 }, (_, i) => book(`book-${String(i).padStart(2, "0")}`))
  const base = stateWith(many, 120, 30)
  const [cur, setCur] = createSignal(0)
  setup = await testRender(() => <QueueScreen state={{ ...base, cursor: cur(), bookName: many[cur()].name }} theme={makeTheme({})} />, { width: 118, height: 23 })
  const view = async () => { await setup!.renderOnce(); return setup!.captureCharFrame() }
  setCur(29)
  expect(await view()).toContain("book-29")
  setCur(28)
  const f = await view()
  expect(f).toContain("book-29")           // the window did not scroll on ↑
  expect(f.split("\n").find((l) => l.includes("book-28"))).toContain("❯")
})

test("name width: CJK straddling the cut and emoji keep nameW exactly", () => {
  expect(strWidth(bookRowText(book("a".repeat(29) + "短い本"), 30, false, false).name)).toBe(30)
  expect(strWidth(bookRowText(book("📚 Книга 📚 про литьё ".repeat(4)), 30, false, false).name)).toBe(30)
  expect(strWidth(bookRowText(book("🔥"), 30, false, false).name)).toBe(30)
})

test("book screen: stages, issues, quality.md", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30), screen: "book" as const }
  const f = await frame(() => <BookScreen state={s} theme={makeTheme({})} />, 118, 23, "Quality report")
  expect(f).toContain("‹ Queue")
  expect(f).toContain("753 pp · djvu · ru · fast")
  expect(f).toContain("✓ layout")
  expect(f).toContain("▸ arbiter")
  expect(f).toContain("Issues  1")
  expect(f).toContain("0004L (p. 8)")
  expect(f).toContain("Quality report")         // markdown rendered (heading without #)
  expect(f).toMatchSnapshot()
})

test("book screen without detail and without quality.md", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30), screen: "book" as const }
  const f1 = await frame(() => <BookScreen state={{ ...s, book: null }} theme={makeTheme({})} />, 118, 23)
  expect(f1).toContain("loading…")
  setup?.renderer.destroy()
  const noQ = { ...DETAIL, quality_md: null, issues: [] }
  const f2 = await frame(() => <BookScreen state={{ ...s, book: noQ }} theme={makeTheme({})} />, 118, 23)
  expect(f2).toContain("quality.md appears when the book is assembled")
  expect(f2).toContain("Issues  0")
})

test("book screen at 80x24 with 7 stages and 12 issues fits the body", async () => {
  const stages = ["layout", "sketches", "drafts", "consensus", "arbiter", "postproc", "assemble"].map((stage, i) => ({
    stage, status: i < 4 ? "done" : i === 4 ? "running" : "pending", seconds: i < 5 ? 100 : null,
    s_per_page: i < 5 ? 1.5 : null, progress: i === 4 ? [3, 10] : null, eta_s: i === 4 ? 60 : null,
  })) as any
  const issues = Array.from({ length: 12 }, (_, i) => `issue ${i}`)
  const s = { ...stateWith(LIBRARY, 80, 24), screen: "book" as const }
  const f = await frame(() => <BookScreen state={{ ...s, book: { ...DETAIL, stages, issues } }} theme={makeTheme({})} />, 78, 17)
  const lines = f.trimEnd().split("\n").filter((_, i, a) => i < a.length)
  expect(f).toContain("+12 more in quality.md")
  expect(f).not.toContain("issue 0")
  const last = lines.map((l, i) => [l.trim(), i] as const).filter(([l]) => l).pop()!
  expect(last[0]).toContain("more in quality.md")   // the lowest non-empty row of the left column is "+N more", in frame
  expect(last[1]).toBeLessThan(17)
})

import { TelemetryScreen } from "../src/screens/Telemetry"
import { pushSnapshot } from "../src/state/history"

function telemetryState(w: number, h: number, log: string[], logScroll = 0): AppState {
  let s = { ...stateWith(LIBRARY, w, h), screen: "telemetry" as const }
  let hist = s.history
  for (let i = 0; i < 30; i++)
    hist = pushSnapshot(hist, snap(LIBRARY, { current: { name: "g", stage: "arbiter", progress: [100 + i, 560], s_per_unit: 28,
                                                         eta_s: 100 } }), i * 20_000)
  return { ...s, history: hist, log, logScroll }
}

test("telemetry: sparklines, model, log", async () => {
  const s = telemetryState(120, 30, ["2026-10-05 17:08:37 arbiter: processed 78", "daemon stopped"])
  const f = await frame(() => <TelemetryScreen state={s} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("GPU memory")
  expect(f).toContain("10.9 / 12.0 GB")
  expect(f).toContain("97 %")
  expect(f).toContain("blocks/min")
  expect(f).toContain("qwen9b_arbiter · techbookocr-qwen9b_arbiter · up 2h11m")
  expect(f).toContain("daemon stopped")
  expect(f).toMatch(/[▁▂▃▄▅▆▇█]{5,}/)
})

test("telemetry at 80x24 fits the body and shows the newest log line", async () => {
  const log = Array.from({ length: 40 }, (_, i) => `log line ${i}`)
  const s = telemetryState(80, 24, log)
  const f = await frame(() => <TelemetryScreen state={s} theme={makeTheme({})} />, 78, 17)
  expect(f).toContain("log line 39")
  expect(f).not.toContain("log line 30")
  const last = f.split("\n").map((l, i) => [l.trim(), i] as const).filter(([l]) => l).pop()!
  expect(last[0]).toContain("log line 39")
  expect(last[1]).toBeLessThan(17)
})

test("telemetry log scroll offset shows older lines; control chars are flattened", async () => {
  const log = Array.from({ length: 40 }, (_, i) => `log line ${i}`)
  const s = telemetryState(80, 24, log, 10)
  const f = await frame(() => <TelemetryScreen state={s} theme={makeTheme({})} />, 78, 17)
  expect(f).toContain("log line 29")
  expect(f).not.toContain("log line 39")
  expect(f).toContain("scrolled 10 lines up")
  setup?.renderer.destroy()
  const g = await frame(() => <TelemetryScreen state={telemetryState(80, 24, ["a\tb\x1b[0mc"])} theme={makeTheme({})} />, 78, 17)
  expect(g).toContain("a b [0mc")
})

const settingsState = (fields: any[], w: number, h: number, cursor: number, draft = {}): AppState => {
  const s = update(stateWith(LIBRARY, w, h), { type: "settingsLoaded", data: { path: "/repo/techbookocr.toml", fields } }).state
  return { ...s, screen: "settings", settings: { ...s.settings!, cursor, draft } }
}

test("settings screen: groups, aligned labels, comments, unsaved", async () => {
  const s = settingsState([
    { section: "library", key: "dir", kind: "path", choices: [], value: "out", comment: "корень библиотеки" },
    { section: "pipeline", key: "mode", kind: "choice", choices: ["fast", "cascade"], value: "fast", comment: null },
  ], 120, 30, 1, { "pipeline.mode": "cascade" })
  const f = await frame(() => <SettingsScreen state={s} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("[library]")
  expect(f).toContain("[pipeline]")
  expect(f).toContain("корень библиотеки")
  expect(f).toContain("‹ cascade ›")
  expect(f).toContain("● unsaved")
  expect(f).toContain("/repo/techbookocr.toml")
})

test("settings at 80×24: 12 fields with comments scroll to keep the cursor visible", async () => {
  const fields = Array.from({ length: 12 }, (_, i) => ({
    section: i < 6 ? "pipeline" : "library", key: `field_${i}`, kind: "int", choices: [], value: i,
    comment: `comment for field ${i}\nsecond line`,
  }))
  const f = await frame(() => <SettingsScreen state={settingsState(fields, 80, 24, 11)} theme={makeTheme({})} />, 78, 17)
  expect(f).toContain("❯ field_11")
  expect(f).toContain("comment for field 11")
  expect(f).not.toContain("field_0 ")
  expect(f.trimEnd().split("\n").length).toBeLessThanOrEqual(17)
})

const twelve = () => Array.from({ length: 12 }, (_, i) => ({
  section: i < 6 ? "pipeline" : "library", key: `field_${i}`, kind: "int", choices: [], value: i,
  comment: `comment for field ${i}\nsecond line`,
}))
const rowOf = (f: string, needle: string) => f.split("\n").findIndex((l) => l.includes(needle))

test("settings: the selected field's section header stays sticky", async () => {
  const f = await frame(() => <SettingsScreen state={settingsState(twelve(), 80, 24, 9)} theme={makeTheme({})} />, 78, 17)
  expect(f).toContain("[library]")
  expect(f).toContain("❯ field_9")
  expect(f.trimEnd().split("\n").length).toBeLessThanOrEqual(17)
  setup?.renderer.destroy()
  const g = await frame(() => <SettingsScreen state={settingsState(twelve(), 80, 24, 11)} theme={makeTheme({})} />, 78, 17)
  expect(rowOf(g, "[library]")).toBe(3)         // header left the window: it sticks as the first row of the list
  expect(g).toContain("❯ field_11 ")
})

test("settings: cursor 0 shows header and first field; moving up shows the field line", async () => {
  const f0 = await frame(() => <SettingsScreen state={settingsState(twelve(), 80, 24, 0)} theme={makeTheme({})} />, 78, 17)
  expect(f0).toContain("[pipeline]")
  expect(f0).toContain("❯ field_0")
  for (let c = 11; c >= 0; c--) {
    setup?.renderer.destroy()
    const f = await frame(() => <SettingsScreen state={settingsState(twelve(), 80, 24, c)} theme={makeTheme({})} />, 78, 17)
    expect(f).toContain(`❯ field_${c} `)
    expect(f).toContain(c < 6 ? "[pipeline]" : "[library]")
  }
})

test("settings: editing keeps the field visible and the caret at the tail of long values", async () => {
  let s = settingsState(twelve(), 80, 24, 10)
  s = { ...s, settings: { ...s.settings!, editing: "x".repeat(80) + "END" } }
  const f = await frame(() => <SettingsScreen state={s} theme={makeTheme({})} />, 78, 17)
  expect(f).toContain("❯ field_10")
  expect(f).toContain("END▏")
})

test("toast takes the footer line, body height is unchanged at 80×24", async () => {
  const base = settingsState(twelve(), 80, 24, 11)
  const plain = await frame(() => <Shell state={base} theme={makeTheme({})} />, 80, 24)
  setup?.renderer.destroy()
  const withToast = { ...base, toast: { text: "saved techbookocr.toml", level: "info" as const, until: 1e12 } }
  const f = await frame(() => <Shell state={withToast} theme={makeTheme({})} />, 80, 24)
  expect(f).toContain("saved techbookocr.toml")
  expect(f).toContain("second line")
  expect(f.split("\n").length).toBe(plain.split("\n").length)
  expect(rowOf(f, "second line")).toBe(rowOf(plain, "second line"))
})

test("help lists bindings by screen (scrollable; tall window shows all)", async () => {
  const s = { ...stateWith(LIBRARY, 120, 90), modal: { kind: "help" as const } }
  const f = await frame(() => <ModalView state={s} theme={makeTheme({})} />, 118, 83)
  expect(f).toContain("Keys")
  expect(f).toContain("Queue")
  expect(f).toContain("run selected now")
  expect(f).toContain("Daemon")
})

test("help at 80×24: box fits the body, first group visible, rest scrolls", async () => {
  const s = { ...stateWith(LIBRARY, 80, 24), modal: { kind: "help" as const } }
  const f = await frame(() => <ModalView state={s} theme={makeTheme({})} />, 78, 17)
  const lines = f.trimEnd().split("\n")
  expect(lines.length).toBeLessThanOrEqual(17)
  expect(f).toContain("Keys")
  expect(f).toContain("Everywhere")
  expect(f).toContain("Queue screen")
  expect(f).not.toContain("Add books")          // the last group is below the visible area
  expect(lines.some((l) => l.includes("╰"))).toBe(true)   // bottom frame within the body
})

test("add books modal lists folders first and marks", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30), modal: { kind: "add" as const, dir: "/books", cursor: 1,
    entries: [{ name: "sub", dir: true }, { name: "a.djvu", dir: false }], marked: ["/books/a.djvu"] } }
  const f = await frame(() => <ModalView state={s} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("Add books")
  expect(f).toContain("/books")
  expect(f).toContain("sub/")
  expect(f).toContain("● a.djvu")
  expect(f).toContain("1 marked")
})

test("add books keeps the cursor visible in a long directory", async () => {
  const entries = Array.from({ length: 40 }, (_, i) => ({ name: `book${String(i).padStart(2, "0")}.pdf`, dir: false }))
  const s = { ...stateWith(LIBRARY, 80, 24), modal: { kind: "add" as const, dir: "/books", cursor: 37, entries, marked: [] } }
  const f = await frame(() => <ModalView state={s} theme={makeTheme({})} />, 78, 17)
  expect(f).toContain("❯ ")
  expect(f).toContain("book37.pdf")
  expect(f).not.toContain("book00.pdf")
  expect(f).toContain("╰")                    // bottom frame within the body
})

test("confirm modal", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30),
    modal: { kind: "confirm" as const, text: "Stop the daemon?", cmd: { kind: "act" as const, action: "daemon_stop" as const } } }
  const f = await frame(() => <ModalView state={s} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("Stop the daemon?")
  expect(f).toContain("y yes")
})

test("shell shows the modal instead of the screen", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30), modal: { kind: "help" as const } }
  const f = await frame(() => <Shell state={s} theme={makeTheme({})} />, 120, 30)
  expect(f).toContain("Keys")
  expect(f).toContain("esc close")
})

test("status strip: columns never touch at 80 columns", async () => {
  const fc = { queued_books: 12, scans: 4200, unknown_scans: 0, seconds: 93600, s_per_scan: 20, basis_books: 3,
               done_today: { books: 0, scans: 0 } }
  const cur = { name: "x", stage: "arbiter", progress: [1, 2], scans: 2 } as any
  for (const w of [80, 120]) {
    const s = update(initialState(w, 24), { type: "snapshot", snap: snap(LIBRARY, { forecast: fc, current: cur }), now: 0 }).state
    const f = await frame(() => <StatusStrip state={s} theme={makeTheme({})} width={w - 2} />, w - 2, 3)
    const line = f.split("\n")[1]
    expect(line).not.toContain("arbiterQueue")
    expect(line).toMatch(/ Queue /)
    expect(line).toContain("GPU")
    if (w === 120) expect(line).toContain("qwen9b_arbiter")
  }
})

test("confirm hint keeps its spacing", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30),
    modal: { kind: "confirm" as const, text: "Stop?", cmd: { kind: "act" as const, action: "daemon_stop" as const } } }
  const f = await frame(() => <ModalView state={s} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("y yes   n no")
})

test("add books title counts marks from several folders", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30), modal: { kind: "add" as const, dir: "/b", cursor: 0,
    entries: [{ name: "z.pdf", dir: false }], marked: ["/a/x.pdf", "/b/z.pdf"] } }
  const f = await frame(() => <ModalView state={s} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("2 marked")
  expect(f).toContain("● z.pdf")
})

test("add books modal shows a marked folder", async () => {
  const s = { ...stateWith(LIBRARY, 120, 30), modal: { kind: "add" as const, dir: "/books", cursor: 1,
    entries: [{ name: "sub", dir: true }, { name: "a.djvu", dir: false }], marked: ["/books/sub"] } }
  const f = await frame(() => <ModalView state={s} theme={makeTheme({})} />, 118, 23)
  expect(f).toContain("● sub/")
  expect(f).toContain("1 marked")
})

test("status strip: dead daemon with queued books keeps the strip at two lines at 80 columns", async () => {
  const fc = { queued_books: 12, scans: 4200, unknown_scans: 0, seconds: 93600, s_per_scan: 20, basis_books: 3,
               done_today: { books: 0, scans: 0 } }
  const s = update(initialState(80, 24), { type: "snapshot", now: 0, snap: snap(LIBRARY, {
    daemon: { alive: false, state: "stopped", heartbeat_age_s: null, run_until: null },
    counts: { queued: 12 }, forecast: fc }) }).state
  const f = await frame(() => <StatusStrip state={s} theme={makeTheme({})} width={78} />, 78, 5)
  const lines = f.split("\n")
  expect(lines[1]).toContain("GPU")
  expect(lines[1]).toContain("→")
  expect(lines.slice(2).join("").trim()).toBe("")
})

test("status strip: unknown scan counts show a dash, not a fake ≈0s", async () => {
  const fc = { queued_books: 5, scans: 0, unknown_scans: 5, seconds: 0, s_per_scan: 20, basis_books: 3,
               done_today: { books: 0, scans: 0 } }
  const s = update(initialState(120, 24), { type: "snapshot", now: 0, snap: snap(LIBRARY, { forecast: fc }) }).state
  const f = await frame(() => <StatusStrip state={s} theme={makeTheme({})} width={118} />, 118, 3)
  expect(f).toContain("Queue 5 books · —")
  expect(f).not.toContain("≈0s")
}
)
