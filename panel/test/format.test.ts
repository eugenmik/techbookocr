import { describe, expect, test } from "bun:test"
import { oneLine } from "../src/format"
import { contextParts, fixColumns, fixIcon, fixSummaryLine, simplifyMarkup } from "../src/fixes-view"
import { bar, fmtDuration, fmtGB, fmtInt, padEnd, padStart, sparkline, strWidth, truncate } from "../src/format"

describe("width-aware text", () => {
  test("truncate by display width", () => {
    expect(truncate("Гиршович_Справочник", 10)).toBe("Гиршович_…")
    expect(strWidth(truncate("Гиршович_Справочник", 10))).toBe(10)
    expect(truncate("短い本の名前です", 7)).toBe("短い本…")   // CJK: 2 columns each
    expect(strWidth(truncate("短い本の名前です", 7))).toBeLessThanOrEqual(7)
    expect(truncate("abc", 5)).toBe("abc")
    expect(truncate("abc", 0)).toBe("")
    expect(truncate("étude", 3)).toBe("ét…")  // a combining mark does not detach from its letter
  })
  test("pad", () => {
    expect(padEnd("ab", 4)).toBe("ab  ")
    expect(padStart("7", 3)).toBe("  7")
    expect(strWidth(padEnd("книга?#с длинным именем", 12))).toBe(12)
  })
})

describe("numbers", () => {
  test("durations", () => {
    expect(fmtDuration(null)).toBe("—")
    expect(fmtDuration(42)).toBe("42s")
    expect(fmtDuration(600)).toBe("10m")
    expect(fmtDuration(3599)).toBe("1h00m")
    expect(fmtDuration(20220)).toBe("5h37m")
    expect(fmtDuration(6 * 86400 + 4 * 3600)).toBe("6d 4h")
  })
  test("ints and GB", () => {
    expect(fmtInt(4310)).toBe("4 310")
    expect(fmtInt(753)).toBe("753")
    expect(fmtGB(11161)).toBe("10.9")
  })
  test("bar and sparkline", () => {
    expect(bar(412, 560, 10)).toBe("███████░░░")
    expect(bar(0, 0, 4)).toBe("░░░░")
    expect(sparkline([0, 50, 100], 3, 100)).toBe("▁▅█")
    expect(sparkline([1, 2, 3, 4, 5], 3)).toBe("▅▇█")   // last `width` values, the maximum is taken over them
    expect(sparkline([], 5)).toBe("")
  })
})

test("oneLine: control chars and whitespace runs become single spaces", () => {
  expect(oneLine("Boom:\n  at x\r\n\tline")).toBe("Boom: at x line")
  expect(oneLine("  a\u0000b  ")).toBe("a b")
})

const F = { id: "0046-1", scan: "0046", page: "34", block: 3, kind: "table", was: "Specific load (t/mm)",
  now: "Specific load (t mm)", state: "reverted" as const, suggested: false, reason: "changes operator",
  decided_by: "rule" as const, before: "d>Roll speed (m/min)</td><td>", after: "</td></tr></thead><tr><td>5.92" }

test("fix view helpers", () => {
  expect(fixIcon(F)).toBe("↶")
  expect(fixIcon({ ...F, state: "applied", suggested: true })).toBe("?")
  expect(simplifyMarkup("<td>a</td><td>b<sub>2</sub></td></tr><tr><td>c<br>d</td>")).toBe("a │ b<sub>2</sub>\nc d")
  const p = contextParts(F)
  expect(p.before).toBe("Roll speed (m/min) │ ")                     // the tag fragment "d>" is cut off
  expect(p.cur).toBe("Specific load (t/mm)")
  expect(p.after).toBe("\n5.92")
  expect([p.otherLabel, p.other]).toEqual(["now", "Specific load (t mm)"])
  expect(fixColumns(78).reason).toBe(0)
  expect(fixColumns(118).reason).toBeGreaterThan(0)
  expect(fixSummaryLine({ total: 25, suggested: 3, reviewed: false })).toBe("Fixes 25 · 3 to review · f")
  expect(fixSummaryLine({ total: 2, suggested: null, reviewed: false })).toBe("Fixes 2 · not reviewed · f")
  expect(fixSummaryLine({ total: 0, suggested: null, reviewed: false })).toBeNull()
  // no "?" at all: nothing to look at (not "reviewed": nobody has opened the new book yet)
  expect(fixSummaryLine({ total: 4, suggested: 0, reviewed: true })).toBe("Fixes 4 · nothing to review · f")
  expect(fixSummaryLine(null)).toBeNull()                          // the summary could not be read
})
