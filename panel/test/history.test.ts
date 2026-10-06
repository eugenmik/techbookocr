import { expect, test } from "bun:test"
import { emptyHistory, HISTORY_MAX, pushSnapshot } from "../src/state/history"
import { LIBRARY, snap } from "./fixtures/state"

const cur = (done: number, stage = "arbiter", name = "g") =>
  snap(LIBRARY, { current: { name, stage, progress: [done, 560], s_per_unit: 28, eta_s: 100 } })

test("gpu series and throughput over the window", () => {
  let h = emptyHistory()
  h = pushSnapshot(h, cur(100), 0)
  h = pushSnapshot(h, cur(110), 5 * 60_000)
  expect(h.gpuMem.at(-1)).toBeCloseTo((11161 / 12288) * 100)
  expect(h.gpuUtil.at(-1)).toBe(97)
  expect(h.rate.at(-1)).toBeCloseTo(2)                   // 10 blocks in 5 minutes
  expect(h.rateUnit).toBe("blocks/min")
})

test("stage change resets throughput samples", () => {
  let h = pushSnapshot(emptyHistory(), cur(100), 0)
  h = pushSnapshot(h, cur(5, "postproc"), 60_000)
  expect(h.samples.length).toBe(1)
  expect(h.rate.at(-1)).toBe(0)
})

test("history is capped", () => {
  let h = emptyHistory()
  for (let i = 0; i < HISTORY_MAX + 10; i++) h = pushSnapshot(h, cur(i), i * 1000)
  expect(h.gpuMem.length).toBe(HISTORY_MAX)
})
