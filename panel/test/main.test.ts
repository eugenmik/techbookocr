import { expect, test } from "bun:test"
import { installExitHandlers, parseCli } from "../src/main"

const none = () => null

test("bridge command from flag, env, PATH", () => {
  expect(parseCli(["--bridge-cmd", "/usr/bin/python3 -m techbookocr", "--out", "/lib"], {}, none))
    .toEqual({ bridgeCmd: ["/usr/bin/python3", "-m", "techbookocr", "bridge", "--out", "/lib"] })
  expect(parseCli(["--config", "/c.toml"], { TECHBOOKOCR_CMD: "bk" }, none))
    .toEqual({ bridgeCmd: ["bk", "bridge", "--config", "/c.toml"] })
  expect(parseCli([], {}, (c) => (c === "techbookocr" ? "/home/u/.local/bin/techbookocr" : null)))
    .toEqual({ bridgeCmd: ["/home/u/.local/bin/techbookocr", "bridge"] })
})

test("no core found", () => {
  const r = parseCli([], {}, none)
  expect("error" in r && r.error).toContain("techbookocr core not found")
})

test("quoted core command with spaces", () => {
  expect(parseCli(["--bridge-cmd", `'/home/me/my venv/bin/python' -m techbookocr`], {}, none))
    .toEqual({ bridgeCmd: ["/home/me/my venv/bin/python", "-m", "techbookocr", "bridge"] })
  expect(parseCli([], { TECHBOOKOCR_CMD: `"/a b/py" -m\\ x` }, none))
    .toEqual({ bridgeCmd: ["/a b/py", "-m x", "bridge"] })
})

test("uncaught error and signals quit exactly once", () => {
  const handlers: Record<string, (e?: unknown) => void> = {}
  const proc = { on: (ev: string, h: (e?: unknown) => void) => { handlers[ev] = h }, exitCode: undefined as number | undefined }
  let quits = 0
  const errs: string[] = []
  installExitHandlers(() => { quits++ }, proc, (m) => errs.push(m))
  handlers.uncaughtException!(new Error("boom"))
  handlers.unhandledRejection!("late")
  handlers.SIGTERM!()
  expect(quits).toBe(1)
  expect(proc.exitCode).toBe(1)
  expect(errs[0]).toContain("boom")
  expect(Object.keys(handlers).sort()).toEqual(["SIGHUP", "SIGTERM", "uncaughtException", "unhandledRejection"])
})
