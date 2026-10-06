// Bridge client: child process, JSON lines, replies by id. If the bridge crashes or hangs,
// pending requests are rejected, and the next request restarts the bridge no sooner
// than delaysMs[attempt] (1, 2, 5, 5… s). stdout lines that are not JSON are ignored.
import type { Subprocess } from "bun"

export type BridgeStatus =
  | { kind: "connecting" }
  | { kind: "ready"; root: string }
  | { kind: "reconnecting"; attempt: number; error: string }

export interface BridgeLike {
  request<T>(op: string, args?: Record<string, unknown>, opts?: { timeoutMs?: number }): Promise<T>
  /** The library changed: subsequent bridge launches take the new --out. */
  retarget(root: string): void
  onStatus(fn: (s: BridgeStatus) => void): void
  close(): void
}

export class BridgeError extends Error {}

interface Pending { resolve: (v: unknown) => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> }

export interface ClientOptions { cmd: string[]; timeoutMs?: number; readyTimeoutMs?: number; delaysMs?: number[] }

type Proc = Subprocess<"pipe", "pipe", "pipe">

// One connection: the bridge process and (until ready) an unfinished launch.
interface Conn {
  proc: Proc
  ready: boolean
  lastStderr: string
  start: { promise: Promise<void>; resolve: () => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> } | null
}

export class BridgeClient implements BridgeLike {
  private conn: Conn | null = null
  private pending = new Map<number, Pending>()
  private nextId = 1
  private attempt = 0
  private nextTryAt = 0
  private listeners: ((s: BridgeStatus) => void)[] = []
  private closed = false

  constructor(private opts: ClientOptions) {}

  retarget(root: string): void {
    const cmd = [...this.opts.cmd]
    const i = cmd.lastIndexOf("--out")
    if (i >= 0 && i + 1 < cmd.length) cmd[i + 1] = root
    else cmd.push("--out", root)
    this.opts = { ...this.opts, cmd }
  }

  onStatus(fn: (s: BridgeStatus) => void): void { this.listeners.push(fn) }

  private emit(s: BridgeStatus) { for (const fn of this.listeners) fn(s) }

  private scheduleRetry(error: string) {
    const delays = this.opts.delaysMs ?? [1000, 2000, 5000]
    this.attempt++
    this.nextTryAt = Date.now() + delays[Math.min(this.attempt - 1, delays.length - 1)]
    this.emit({ kind: "reconnecting", attempt: this.attempt, error })
  }

  // Fails a specific connection: kills the process, rejects the launch and all requests.
  // Calls from old (already replaced) connections are ignored.
  private fail(conn: Conn, error: string) {
    if (this.conn !== conn) return
    this.conn = null
    const msg = conn.lastStderr ? `${error} (${conn.lastStderr})` : error
    try { conn.proc.kill() } catch {}
    if (conn.start) { clearTimeout(conn.start.timer); conn.start.reject(new BridgeError(msg)); conn.start = null }
    for (const [, w] of this.pending) { clearTimeout(w.timer); w.reject(new BridgeError(msg)) }
    this.pending.clear()
    if (!this.closed) this.scheduleRetry(msg)
  }

  private async pumpStdout(conn: Conn) {
    const decoder = new TextDecoder()
    let buf = ""
    try {
      for await (const chunk of conn.proc.stdout) {
        if (this.conn !== conn) return
        buf += decoder.decode(chunk, { stream: true })
        let i: number
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i).trim()
          buf = buf.slice(i + 1)
          if (line.startsWith("{")) this.onLine(conn, line)
          if (this.conn !== conn) return
        }
      }
    } catch {}
    // stderr may not have been fully read yet: give it time to reach the error message
    await conn.proc.exited.catch(() => {})
    await Bun.sleep(20)
    this.fail(conn, "bridge exited")
  }

  private async pumpStderr(conn: Conn) {
    const decoder = new TextDecoder()
    let buf = ""
    try {
      for await (const chunk of conn.proc.stderr) {
        buf += decoder.decode(chunk, { stream: true })
        const lines = buf.split("\n")
        buf = lines.pop() ?? ""
        for (const l of lines) if (l.trim()) conn.lastStderr = l.trim()
      }
    } catch {}
    if (buf.trim()) conn.lastStderr = buf.trim()
  }

  private onLine(conn: Conn, line: string) {
    let msg: any
    try { msg = JSON.parse(line) } catch { return }
    if (!msg || typeof msg !== "object") return
    if (msg.ready !== undefined) {
      if (conn.ready) return
      if (msg.ready) {
        conn.ready = true
        if (conn.start) { clearTimeout(conn.start.timer); conn.start.resolve(); conn.start = null }
        this.attempt = 0
        this.emit({ kind: "ready", root: String(msg.root ?? "") })
      } else this.fail(conn, `bridge not ready: ${msg.error ?? "unknown error"}`)
      return
    }
    const w = this.pending.get(msg.id)
    if (!w) return
    this.pending.delete(msg.id)
    clearTimeout(w.timer)
    if (msg.ok) w.resolve(msg.data)
    else w.reject(new BridgeError(String(msg.error ?? "error")))
  }

  private ensure(): Promise<Conn> {
    const cur = this.conn
    if (cur) return cur.ready ? Promise.resolve(cur) : cur.start!.promise.then(() => cur)
    if (Date.now() < this.nextTryAt) return Promise.reject(new BridgeError("reconnecting"))
    this.emit({ kind: "connecting" })
    let proc: Proc
    try {
      proc = Bun.spawn(this.opts.cmd, { stdin: "pipe", stdout: "pipe", stderr: "pipe" })
    } catch (e) {
      const msg = `cannot start bridge: ${(e as Error).message}`
      this.scheduleRetry(msg)
      return Promise.reject(new BridgeError(msg))
    }
    let resolve!: () => void
    let reject!: (e: Error) => void
    const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej })
    const conn: Conn = { proc, ready: false, lastStderr: "", start: null }
    conn.start = {
      promise, resolve, reject,
      timer: setTimeout(() => this.fail(conn, "bridge did not report ready"), this.opts.readyTimeoutMs ?? 15_000),
    }
    this.conn = conn
    void this.pumpStdout(conn)
    void this.pumpStderr(conn)
    return promise.then(() => conn)
  }

  async request<T>(op: string, args: Record<string, unknown> = {}, opts: { timeoutMs?: number } = {}): Promise<T> {
    if (this.closed) throw new BridgeError("closed")
    const conn = await this.ensure()
    if (this.closed) throw new BridgeError("closed")
    if (this.conn !== conn) throw new BridgeError("bridge exited")
    const id = this.nextId++
    return new Promise<T>((resolve, reject) => {
      // the timeout fails the bridge; fail() will reject this request itself
      const timer = setTimeout(() => this.fail(conn, `timeout: ${op}`), opts.timeoutMs ?? this.opts.timeoutMs ?? 10_000)
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer })
      try {
        conn.proc.stdin.write(JSON.stringify({ id, op, ...args }) + "\n")
        conn.proc.stdin.flush()
      } catch {
        this.fail(conn, "bridge exited")
      }
    })
  }

  close(): void {
    this.closed = true
    const conn = this.conn
    this.conn = null
    if (conn?.start) { clearTimeout(conn.start.timer); conn.start.reject(new BridgeError("closed")); conn.start = null }
    for (const [, w] of this.pending) { clearTimeout(w.timer); w.reject(new BridgeError("closed")) }
    this.pending.clear()
    if (conn) {
      try { conn.proc.stdin.end() } catch {}
      setTimeout(() => { try { conn.proc.kill() } catch {} }, 2000).unref?.()
    }
  }
}
