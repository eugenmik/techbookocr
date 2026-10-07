import { expect, spyOn, test } from "bun:test"
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { listDir, messageLevel, runCommand } from "../src/effects"

test("listDir follows symlinks, skips broken ones", () => {
  const root = mkdtempSync(join(tmpdir(), "listdir-"))
  const real = mkdtempSync(join(tmpdir(), "listdir-real-"))
  mkdirSync(join(real, "folder"))
  writeFileSync(join(real, "b.djvu"), "x")
  writeFileSync(join(real, "n.txt"), "x")
  symlinkSync(join(real, "folder"), join(root, "linkdir"))
  symlinkSync(join(real, "b.djvu"), join(root, "link.djvu"))
  symlinkSync(join(real, "n.txt"), join(root, "link.txt"))
  symlinkSync(join(real, "missing.pdf"), join(root, "broken.pdf"))
  expect(listDir(root)).toEqual([{ name: "linkdir", dir: true }, { name: "link.djvu", dir: false }])
})

// All message forms from src/techbookocr/tui/actions.py (book_action, bump_priority, start_daemon, run_books,
// toggle_pause, stop_daemon, add_books).
const OK_MESSAGES = [
  "command skip alpha queued", "skip alpha → skipped", "retry alpha → queued", "alpha: priority 3",
  "daemon already running", "daemon started, log: /out/daemon.log",
  "select a book first — cursor or space to mark", "nothing to run — selected books are done",
  "alpha → daemon starting", "3 books, pause after alpha → daemon starting",
  "daemon resumed — running full queue", "daemon is not running", "daemon is stopping: pause/resume unavailable",
  "command pause queued", "command stop queued",
  "added: 2, skipped: 0 — daemon is not running; press d to process the queue",
  "added: 1, skipped: 1 — daemon is running, books will be processed in turn",
  "added: 0, skipped: 1 — already in queue or not a book",
]
const ERR_MESSAGES = [
  "retry alpha rejected: book is done", "no book ghost", "error skip alpha: database is locked",
  "error priority alpha: boom", "error run: boom", "error: boom",
  "daemon failed to start — see /out/daemon.log", "daemon not started: [Errno 2] No such file",
  "not added: bad path", "cannot open folder", "unknown op",
]

test("messageLevel: errors red, everything else info", () => {
  for (const m of OK_MESSAGES) expect([m, messageLevel(m)]).toEqual([m, "info"])
  for (const m of ERR_MESSAGES) expect([m, messageLevel(m)]).toEqual([m, "error"])
})

test("act/add messages become toasts with the classified level", async () => {
  const client = { request: async () => ({ messages: ["skip a → skipped", "no book b"], added: [], skipped: [] }) }
  const acts = await runCommand({ kind: "act", action: "skip", books: ["a", "b"] }, { client: client as never, now: () => 1 })
  expect(acts.filter((a) => a.type === "toast").map((a) => (a as { level: string }).level)).toEqual(["info", "error"])
})

const FIELDS = { path: "/repo/techbookocr.toml", fields: [] }

function fakeClient(replies: Record<string, unknown>) {
  const calls: { op: string; args: unknown; opts: unknown }[] = []
  const retargets: string[] = []
  const client = {
    request: async (op: string, args?: unknown, opts?: unknown) => { calls.push({ op, args, opts }); return replies[op] },
    retarget: (r: string) => { retargets.push(r) },
  }
  return { client: client as never, calls, retargets }
}

test("settings_set and settings_get replies retarget the bridge to the reported root", async () => {
  const c = fakeClient({ settings_set: { root: "/new/lib" }, settings_get: { ...FIELDS, root: "/new/lib" } })
  await runCommand({ kind: "saveSettings", updates: [] }, { client: c.client, now: () => 1 })
  expect(c.retargets).toEqual(["/new/lib", "/new/lib"])
  const g = fakeClient({ settings_get: { ...FIELDS, root: "/other" } })
  await runCommand({ kind: "loadSettings" }, { client: g.client, now: () => 1 })
  expect(g.retargets).toEqual(["/other"])
})

test("add waits up to 120 s for the bridge", async () => {
  const c = fakeClient({ add: { messages: ["added: 1, skipped: 0"], added: ["a"], skipped: [], skipped_total: 0 } })
  await runCommand({ kind: "add", paths: ["/x"] }, { client: c.client, now: () => 1 })
  expect(c.calls[0]!.opts).toEqual({ timeoutMs: 120_000 })
})

// $EDITOR: a fake editor writes its arguments to a file; suspend runs fn immediately.
function fakeEditor() {
  const dir = mkdtempSync(join(tmpdir(), "editor-"))
  const script = join(dir, "ed.sh")
  const log = join(dir, "args.txt")
  writeFileSync(script, `#!/bin/sh\necho "$@" > ${log}\n`)
  chmodSync(script, 0o755)
  return { script, log, dir }
}

async function withEditor(value: string, fn: () => Promise<void>) {
  const old = { v: process.env.VISUAL, e: process.env.EDITOR }
  delete process.env.VISUAL
  process.env.EDITOR = value
  try { await fn() } finally {
    if (old.v === undefined) delete process.env.VISUAL; else process.env.VISUAL = old.v
    if (old.e === undefined) delete process.env.EDITOR; else process.env.EDITOR = old.e
  }
}

test("editToml: runs the editor under suspend, then dispatches fresh settingsLoaded", async () => {
  const ed = fakeEditor()
  await withEditor(ed.script, async () => {
    const order: string[] = []
    const client = { request: async () => { order.push(existsSync(ed.log) ? "get-after-edit" : "get-before-edit"); return { ...FIELDS, root: "/r" } },
                      retarget: () => {} }
    const acts = await runCommand({ kind: "editToml", path: "/repo/techbookocr.toml" },
      { client: client as never, now: () => 1, suspend: (fn) => { order.push("suspend"); fn() } })
    expect(order).toEqual(["suspend", "get-after-edit"])
    expect(readFileSync(ed.log, "utf8").trim()).toBe("/repo/techbookocr.toml")
    expect(acts).toEqual([{ type: "settingsLoaded", data: { ...FIELDS, root: "/r" } }])
  })
})

test("editToml: $EDITOR with arguments is split into words", async () => {
  const ed = fakeEditor()
  await withEditor(`${ed.script} --wait`, async () => {
    const client = { request: async () => FIELDS, retarget: () => {} }
    const acts = await runCommand({ kind: "editToml", path: "/repo/techbookocr.toml" },
      { client: client as never, now: () => 1, suspend: (fn) => fn() })
    expect(acts[0]!.type).toBe("settingsLoaded")
    expect(readFileSync(ed.log, "utf8").trim()).toBe("--wait /repo/techbookocr.toml")
  })
})

test("editToml: a broken toml after editing becomes an error toast, not a crash", async () => {
  const ed = fakeEditor()
  await withEditor(ed.script, async () => {
    const client = { request: async () => { throw new Error("techbookocr.toml: bad") }, retarget: () => {} }
    const acts = await runCommand({ kind: "editToml", path: "/p" }, { client: client as never, now: () => 1, suspend: (fn) => fn() })
    expect(acts).toEqual([{ type: "toast", text: "techbookocr.toml: bad", level: "error", now: 1 }])
  })
})

test("fix commands call the bridge with a long timeout for the journal", async () => {
  const calls: any[] = []
  const client: any = { request: async (op: string, args: any, opts: any) => {
    calls.push([op, args, opts])
    if (op === "fixes") return { fixes: [], counts: { applied: 0, reverted: 0, suggested: 0, not_found: 0 }, editable: true, why_not: null }
    return { fix: { id: "0046-1", state: "reverted" }, counts: { applied: 0, reverted: 1, suggested: 0, not_found: 0 } }
  }, retarget() {} }
  const ctx = { client, now: () => 0 }
  expect((await runCommand({ kind: "loadFixes", book: "b" }, ctx))[0].type).toBe("fixesLoaded")
  expect(calls[0]).toEqual(["fixes", { book: "b" }, { timeoutMs: 60_000 }])
  const acts = await runCommand({ kind: "fixSet", book: "b", id: "0046-1", applied: false }, ctx)
  expect(calls[1].slice(0, 2)).toEqual(["fix_set", { book: "b", fix: "0046-1", applied: false }])
  expect(acts.map((a) => a.type)).toEqual(["fixUpdated", "toast"])
  await runCommand({ kind: "fixKeep", book: "b", id: "0046-1" }, ctx)
  expect(calls[2].slice(0, 2)).toEqual(["fix_keep", { book: "b", fix: "0046-1" }])
  expect((await runCommand({ kind: "notify", text: "x", level: "error" }, ctx))[0]).toMatchObject({ type: "toast", text: "x", level: "error" })
})

test("a failed fixes load gives an error toast and a fixesFailed action", async () => {
  const client: any = { request: async () => { throw new Error("bridge timeout") }, retarget() {} }
  const acts = await runCommand({ kind: "loadFixes", book: "b" }, { client, now: () => 5 })
  expect(acts).toEqual([{ type: "toast", text: "bridge timeout", level: "error", now: 5 },
                        { type: "fixesFailed", book: "b", error: "bridge timeout" }])
})

test("a failed fixSet/fixKeep toasts the error and reloads the journal from the bridge", async () => {
  const data = { fixes: [], counts: { applied: 0, reverted: 0, suggested: 0, not_found: 1 }, editable: true, why_not: null }
  const calls: string[] = []
  const client: any = { request: async (op: string) => {
    calls.push(op)
    if (op === "fixes") return data
    throw new Error("0046-1: fix location changed")
  }, retarget() {} }
  for (const cmd of [{ kind: "fixSet", book: "b", id: "0046-1", applied: false } as const,
                     { kind: "fixKeep", book: "b", id: "0046-1" } as const]) {
    calls.length = 0
    const acts = await runCommand(cmd, { client, now: () => 7 })
    expect(acts).toEqual([{ type: "toast", text: "0046-1: fix location changed", level: "error", now: 7 },
                          { type: "fixesLoaded", book: "b", data }])
    expect(calls).toEqual([cmd.kind === "fixSet" ? "fix_set" : "fix_keep", "fixes"])
  }
  // the reload fails too: only the toast about the original error, the screen stays as it was
  const dead: any = { request: async () => { throw new Error("bridge down") }, retarget() {} }
  expect(await runCommand({ kind: "fixKeep", book: "b", id: "x" }, { client: dead, now: () => 1 }))
    .toEqual([{ type: "toast", text: "bridge down", level: "error", now: 1 }])
})

test("openFile runs xdg-open on the file and toasts its name", async () => {
  const spawn = spyOn(Bun, "spawn").mockImplementation((() => ({})) as never)
  const file = join(mkdtempSync(join(tmpdir(), "crop-")), "0046-b3.webp")
  writeFileSync(file, "x")
  try {
    const acts = await runCommand({ kind: "openFile", path: file }, { client: {} as never, now: () => 7 })
    expect(spawn).toHaveBeenCalledTimes(1)
    expect(spawn.mock.calls[0]![0]).toEqual(["xdg-open", file])
    expect(acts).toEqual([{ type: "toast", text: "opened 0046-b3.webp", level: "info", now: 7 }])
  } finally {
    spawn.mockRestore()
  }
})

test("openFile of a missing file is an error toast, xdg-open is not run", async () => {
  const spawn = spyOn(Bun, "spawn").mockImplementation((() => ({})) as never)
  try {
    const acts = await runCommand({ kind: "openFile", path: "/nonexistent/fixes/x.webp" }, { client: {} as never, now: () => 7 })
    expect(spawn).not.toHaveBeenCalled()
    expect(acts).toEqual([{ type: "toast", text: "scan fragment missing: /nonexistent/fixes/x.webp", level: "error", now: 7 }])
  } finally {
    spawn.mockRestore()
  }
})
