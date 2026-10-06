import { afterEach, expect, test } from "bun:test"
import { BridgeClient, BridgeError, type BridgeStatus } from "../src/bridge/client"

const fake = (mode: string) => [process.execPath, `${import.meta.dir}/fixtures/fake-bridge.ts`, mode]
let client: BridgeClient | null = null
afterEach(() => client?.close())

// Retries the request while the bridge is "reconnecting" (up to ~1 s).
async function retry(c: BridgeClient, op: string): Promise<any> {
  for (let i = 0; i < 50; i++) {
    try { return await c.request<any>(op) } catch (e) {
      if (!String((e as Error).message).includes("reconnecting")) throw e
      await Bun.sleep(20)
    }
  }
  throw new Error("still reconnecting")
}

test("request/response by id, ready reported", async () => {
  const seen: BridgeStatus[] = []
  client = new BridgeClient({ cmd: fake("normal") })
  client.onStatus((s) => seen.push(s))
  const [a, b] = await Promise.all([client.request<any>("snapshot"), client.request<any>("book", { name: "x" })])
  expect(a.echo).toBe("snapshot")
  expect(b.echo).toBe("book")
  expect(seen.some((s) => s.kind === "ready" && s.root === "/tmp/lib")).toBe(true)
})

test("ok:false becomes BridgeError, client keeps working", async () => {
  client = new BridgeClient({ cmd: fake("normal") })
  await expect(client.request("fail")).rejects.toThrow("boom")
  expect((await client.request<any>("x")).echo).toBe("x")
})

test("non-JSON stdout lines are ignored", async () => {
  client = new BridgeClient({ cmd: fake("noisy") })
  expect((await client.request<any>("a")).echo).toBe("a")
  expect((await client.request<any>("b")).echo).toBe("b")
})

test("bridge death rejects pending and reconnects after delay", async () => {
  const seen: BridgeStatus[] = []
  client = new BridgeClient({ cmd: fake("die-after-1"), delaysMs: [50, 50] })
  client.onStatus((s) => seen.push(s))
  await client.request("first")
  await expect(client.request("second")).rejects.toBeInstanceOf(BridgeError)
  expect(seen.some((s) => s.kind === "reconnecting")).toBe(true)
  await expect(client.request("too-early")).rejects.toThrow("reconnecting")
  expect((await retry(client, "again")).echo).toBe("again")
})

test("timeout kills the bridge", async () => {
  client = new BridgeClient({ cmd: fake("slow"), timeoutMs: 200, delaysMs: [10] })
  await expect(client.request("slow")).rejects.toThrow("timeout")
  expect((await retry(client, "fast")).echo).toBe("fast")
})

test("bridge that never reports ready", async () => {
  client = new BridgeClient({ cmd: fake("not-ready"), readyTimeoutMs: 300, delaysMs: [10] })
  await expect(client.request("x")).rejects.toThrow("ready")
})

test("missing executable", async () => {
  client = new BridgeClient({ cmd: ["/nonexistent/techbookocr", "bridge"], delaysMs: [10] })
  await expect(client.request("x")).rejects.toBeInstanceOf(BridgeError)
})

test("ready:false rejects with the error text", async () => {
  client = new BridgeClient({ cmd: fake("ready-false"), delaysMs: [10] })
  await expect(client.request("x")).rejects.toThrow("bridge not ready: bad toml")
})

test("ready:false followed by sleep does not hang", async () => {
  client = new BridgeClient({ cmd: fake("ready-false-sleep"), delaysMs: [10] })
  await expect(client.request("x")).rejects.toThrow("bad toml")
})

test("exit before ready rejects and surfaces stderr", async () => {
  const seen: BridgeStatus[] = []
  client = new BridgeClient({ cmd: fake("exit-before-ready"), delaysMs: [10] })
  client.onStatus((s) => seen.push(s))
  await expect(client.request("x")).rejects.toThrow("exited")
  const r = seen.find((s) => s.kind === "reconnecting") as any
  expect(r.error).toContain("Traceback: bad config")
})

test("close() while starting rejects promptly", async () => {
  client = new BridgeClient({ cmd: fake("not-ready"), readyTimeoutMs: 30_000 })
  const p = client.request("x")
  const t0 = Date.now()
  await Bun.sleep(50)
  client.close()
  await expect(p).rejects.toThrow("closed")
  expect(Date.now() - t0).toBeLessThan(1000)
})

test("stale ready timer does not kill the next bridge", async () => {
  const seen: BridgeStatus[] = []
  client = new BridgeClient({ cmd: fake("die-after-1"), readyTimeoutMs: 1000, delaysMs: [10] })
  client.onStatus((s) => seen.push(s))
  await client.request("first")
  await expect(client.request("second")).rejects.toBeInstanceOf(BridgeError)
  expect((await retry(client, "again")).echo).toBe("again")
  const before = seen.length
  await Bun.sleep(1200) // the old ready timer (1 s) should have fired already if it was not cleared
  expect(seen.length).toBe(before)
})

test("retarget replaces the --out value of the next spawn", async () => {
  client = new BridgeClient({ cmd: [...fake("die-after-1"), "--out", "/a", "--config", "c.toml"], delaysMs: [20] })
  expect((await client.request<any>("first")).argv).toEqual(["--out", "/a", "--config", "c.toml"])
  client.retarget("/b")
  await expect(client.request("second")).rejects.toBeInstanceOf(BridgeError)
  expect((await retry(client, "again")).argv).toEqual(["--out", "/b", "--config", "c.toml"])
})

test("retarget appends --out when the command had none", async () => {
  client = new BridgeClient({ cmd: fake("die-after-1"), delaysMs: [20] })
  await client.request("first")
  client.retarget("/b")
  await expect(client.request("second")).rejects.toBeInstanceOf(BridgeError)
  expect((await retry(client, "again")).argv).toEqual(["--out", "/b"])
})

test("per-request timeout overrides the default", async () => {
  client = new BridgeClient({ cmd: fake("normal"), timeoutMs: 100, delaysMs: [10] })
  await client.request("warmup")
  expect((await client.request<any>("sleep300", {}, { timeoutMs: 3000 })).echo).toBe("sleep300")
  await expect(client.request("sleep300")).rejects.toThrow("timeout")
})
