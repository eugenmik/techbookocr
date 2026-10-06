// Entry point of techbookocr-tui: arguments, core lookup, renderer, App. Exit only via renderer.destroy().
import { parseArgs } from "node:util"
import { createCliRenderer } from "@opentui/core"
import { render } from "@opentui/solid"
import { App } from "./App"
import { BridgeClient } from "./bridge/client"
import { splitWords } from "./shell"

/** Any exit goes through a single quit(): signals and unhandled errors; exit code 1 without process.exit. */
export function installExitHandlers(
  quit: () => void,
  proc: { on(ev: string, h: (e?: unknown) => void): unknown; exitCode?: number | string | null },
  report: (msg: string) => void = (m) => console.error(m),
): void {
  let once = false
  const run = () => { if (!once) { once = true; quit() } }
  const fail = (e?: unknown) => {
    run()
    report(`techbookocr-tui: ${e instanceof Error ? (e.stack ?? e.message) : String(e)}`)
    proc.exitCode = 1
  }
  proc.on("uncaughtException", fail)
  proc.on("unhandledRejection", fail)
  proc.on("SIGTERM", run)
  proc.on("SIGHUP", run)
}

export function parseCli(argv: string[], env: Record<string, string | undefined>,
                         which: (cmd: string) => string | null): { bridgeCmd: string[] } | { error: string } {
  const { values } = parseArgs({
    args: argv,
    options: { out: { type: "string" }, config: { type: "string" }, "bridge-cmd": { type: "string" } },
    strict: true,
  })
  const raw = values["bridge-cmd"] ?? env.TECHBOOKOCR_CMD ?? which("techbookocr")
  if (!raw) return { error: "techbookocr core not found: pass --bridge-cmd, set TECHBOOKOCR_CMD, or put techbookocr on PATH" }
  const core = splitWords(raw)
  const extra = [...(values.out ? ["--out", values.out] : []), ...(values.config ? ["--config", values.config] : [])]
  return { bridgeCmd: [...core, "bridge", ...extra] }
}

async function main(): Promise<number> {
  let parsed: ReturnType<typeof parseCli>
  try {
    parsed = parseCli(Bun.argv.slice(2), process.env, (c) => Bun.which(c))
  } catch (e) {
    console.error(`techbookocr-tui: ${(e as Error).message}`)
    return 2
  }
  if ("error" in parsed) { console.error(`techbookocr-tui: ${parsed.error}`); return 2 }
  if (!process.stdout.isTTY || !process.stdin.isTTY) {
    console.error("techbookocr-tui: not a terminal — use `techbookocr status` for plain output")
    return 2
  }
  const client = new BridgeClient({ cmd: parsed.bridgeCmd })
  const renderer = await createCliRenderer({ exitOnCtrlC: false, targetFps: 30 })
  let done = false
  const quit = () => {
    if (done) return
    done = true
    try { client.close() } finally { renderer.destroy() }
  }
  installExitHandlers(quit, process)
  const suspend = (fn: () => void) => {
    renderer.suspend()
    try { fn() } finally { renderer.resume() }
  }
  try {
    render(() => <App client={client} onQuit={quit} suspend={suspend} />, renderer)
  } catch (e) {
    quit()
    console.error(`techbookocr-tui: ${(e as Error).stack ?? e}`)
    return 1
  }
  return 0
}

if (import.meta.main) {
  const code = await main()
  if (code !== 0) process.exitCode = code
}
