import { expect, test } from "bun:test"
import { CARD_W, COL, queueLayout } from "../src/layout"

test("card only from 110 columns", () => {
  expect(queueLayout(109, 35).cardW).toBe(0)
  expect(queueLayout(110, 35).cardW).toBe(CARD_W)
})

test("name column takes the rest", () => {
  const l = queueLayout(120, 35)
  expect(l.leftW).toBe(120 - 2 - CARD_W - 4)
  expect(l.nameW).toBe(l.leftW - COL.ptr - COL.state - COL.detail - COL.prio - 6)
  expect(l.tableH).toBeGreaterThan(5)
})

test("small window keeps positive sizes", () => {
  const l = queueLayout(80, 24)
  expect(l.cardW).toBe(0)
  expect(l.eventsH).toBe(3)
  expect(l.tableH).toBeGreaterThanOrEqual(3)
  expect(l.nameW).toBeGreaterThanOrEqual(10)
})
