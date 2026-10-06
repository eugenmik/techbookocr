// Fake bridge for client tests. Mode is argv[2]: normal | noisy | die-after-1 | slow | not-ready
export {}
const mode = process.argv[2] ?? "normal"
if (mode === "exit-before-ready") {
  console.error("Traceback: bad config")
  process.exit(2)
}
if (mode === "ready-false" || mode === "ready-false-sleep") {
  console.log(JSON.stringify({ ready: false, v: 1, error: "bad toml" }))
  if (mode === "ready-false-sleep") await Bun.sleep(60_000)
  process.exit(1)
}
if (mode === "not-ready") {
  console.log("starting...")
  await Bun.sleep(60_000)
}
if (mode === "noisy") console.log("warning: something printed to stdout")
console.log(JSON.stringify({ ready: true, v: 1, root: "/tmp/lib", config: null }))
let n = 0
for await (const line of console) {
  const req = JSON.parse(line)
  n++
  if (mode === "noisy") console.log("noise between replies")
  if (mode === "die-after-1" && n > 1) { console.error("boom trace"); process.exit(3) }
  if (mode === "slow" && req.op === "slow") await Bun.sleep(5_000)
  if (req.op === "sleep300") await Bun.sleep(300)
  if (req.op === "fail") console.log(JSON.stringify({ id: req.id, ok: false, error: "boom" }))
  else console.log(JSON.stringify({ id: req.id, ok: true, data: { echo: req.op, n, argv: process.argv.slice(3) } }))
}
