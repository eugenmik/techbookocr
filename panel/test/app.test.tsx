import { afterEach, expect, test } from "bun:test"
import { testRender } from "@opentui/solid"
import { App } from "../src/App"
import type { BridgeLike, BridgeStatus } from "../src/bridge/client"
import { makeTheme } from "../src/theme"
import { DETAIL, LIBRARY, snap } from "./fixtures/state"

class FakeBridge implements BridgeLike {
  calls: [string, Record<string, unknown>][] = []
  fail = false
  private fns: ((s: BridgeStatus) => void)[] = []
  constructor(private responses: Record<string, unknown> = {}) {}
  onStatus(fn: (s: BridgeStatus) => void) { this.fns.push(fn) }
  status(s: BridgeStatus) { this.fns.forEach((f) => f(s)) }
  async request<T>(op: string, args: Record<string, unknown> = {}): Promise<T> {
    this.calls.push([op, args])
    if (this.fail) throw new Error("bridge exited")
    if (op === "snapshot") return snap(LIBRARY) as T
    if (op === "book") return DETAIL as T
    if (op === "log_tail") return { lines: ["daemon started"] } as T
    if (op === "settings_get") return { path: "/repo/techbookocr.toml", fields: [] } as T
    return (this.responses[op] ?? { messages: ["ok"] }) as T
  }
  retarget() {}
  close() {}
}

let setup: Awaited<ReturnType<typeof testRender>> | null = null
afterEach(() => { setup?.renderer.destroy(); setup = null })

async function mount(w = 120, h = 35, bridge = new FakeBridge()) {
  let quit = 0
  setup = await testRender(() => <App client={bridge} onQuit={() => quit++} pollMs={50} slowPollMs={100} />,
                           { width: w, height: h })
  await setup.waitForFrame((f) => f.includes("Queue 1 books") || f.includes("Queue"))
  return { setup, bridge, quits: () => quit }
}

test("chrome: status strip, tabs, footer", async () => {
  const { setup } = await mount()
  const f = await setup.waitForFrame((f) => f.includes("running"))
  expect(f).toContain("techbookocr")
  expect(f).toContain("/home/u/out")
  expect(f).toContain("● running")
  expect(f).toContain("GPU 10.9/12.0 GB · 97%")
  expect(f).toContain("1 Queue")
  expect(f).toContain("4 Settings")
  expect(f).toContain("? keys")
  expect(f).toContain("t stop")
})

test("too small window shows a message and recovers", async () => {
  const { setup } = await mount()
  setup.resize(70, 20)
  let f = await setup.waitForFrame((f) => f.includes("window too small"))
  expect(f).toContain("need 80×24, have 70×20")
  setup.resize(120, 35)
  f = await setup.waitForFrame((f) => f.includes("1 Queue"))
  expect(f).not.toContain("window too small")
})

test("bridge outage keeps last data and shows reconnecting", async () => {
  const { setup, bridge } = await mount()
  await setup.waitForFrame((f) => f.includes("running"))
  bridge.fail = true
  bridge.status({ kind: "reconnecting", attempt: 2, error: "bridge exited" })
  const f = await setup.waitForFrame((f) => f.includes("reconnecting"))
  expect(f).toContain("attempt 2")
  expect(f).toContain("stale")
  expect(f).toContain("Гиршович")
})

test("q calls onQuit, digits switch tabs", async () => {
  const { setup, quits } = await mount()
  setup.mockInput.pressKey("3")
  await setup.waitForFrame((f) => f.includes("GPU memory"))
  setup.mockInput.pressKey("q")
  await setup.waitFor(() => quits() === 1)
})

test.skipIf(!makeTheme().color)("theme colors reach the screen (span fg goes through style)", async () => {
  const { setup } = await mount()
  await setup.waitForFrame((f) => f.includes("running"))
  const cells = setup.captureSpans().lines.flatMap((l) => l.spans)
  const tab = cells.find((s) => s.text.includes("[1 Queue]"))
  expect(tab).toBeDefined()
  const c = tab!.fg as unknown as { buffer: ArrayLike<number> }
  expect([0, 1, 2].map((i) => Math.round(c.buffer[i]))).toEqual([0x5f, 0xaf, 0xd7])
})

test("action result becomes a toast", async () => {
  const bridge = new FakeBridge({ act: { messages: ["skip a → skipped"] } })
  const { setup } = await mount(120, 35, bridge)
  await setup.waitForFrame((f) => f.includes("Гиршович"))
  setup.mockInput.pressKey("s")
  const f = await setup.waitForFrame((f) => f.includes("skip a → skipped"))
  expect(bridge.calls.some(([op, a]) => op === "act" && a.action === "skip")).toBe(true)
})

test("tab bar highlight follows the active screen", async () => {
  const { setup } = await mount()
  setup.mockInput.pressKey("3")
  let f = await setup.waitForFrame((f) => f.includes("[3 Telemetry]"))
  expect(f).not.toContain("[1 Queue]")
  setup.mockInput.pressKey("1")
  f = await setup.waitForFrame((f) => f.includes("[1 Queue]"))
  expect(f).not.toContain("[3 Telemetry]")
})
