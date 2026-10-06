import { describe, expect, test } from "bun:test"
import { oneLine } from "../src/format"
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
