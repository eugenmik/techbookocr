import { describe, expect, test } from "bun:test"
import { readableMath } from "../src/math-text"

describe("readableMath: subscripts and superscripts", () => {
  test("<sub>/<sup> → Unicode if every character has such a form", () => {
    expect(readableMath("σ<sub>-1p</sub>")).toBe("σ₋₁ₚ")
    expect(readableMath("10<sup>-6</sup>")).toBe("10⁻⁶")
    expect(readableMath("$x^{2}$")).toBe("x²")
    expect(readableMath("$x^{max}$")).toBe("xᵐᵃˣ")
    expect(readableMath("$a_{i+1}$")).toBe("aᵢ₊₁")
    expect(readableMath("$x_1$")).toBe("x₁")
    expect(readableMath("σ<sub>−1</sub>")).toBe("σ₋₁")           // a real minus sign
    expect(readableMath("t<sup>°</sup>")).toBe("t°")
  })
  test("otherwise the compact notation (Cyrillic letters have no Unicode script forms)", () => {
    expect(readableMath("a<sub>н</sub>")).toBe("a_н")
    expect(readableMath("σ<sub>В</sub>")).toBe("σ_В")
    expect(readableMath("$A_{\\text{ст}}$")).toBe("A_{ст}")
    expect(readableMath("$x^{кр}$")).toBe("x^{кр}")
    expect(readableMath("x<sup>кр</sup>")).toBe("x^{кр}")
    expect(readableMath("$x^в$")).toBe("x^в")
  })
})

describe("readableMath: LaTeX", () => {
  test("fractions, roots, symbols", () => {
    expect(readableMath("$\\frac{a+b}{c}$")).toBe("(a+b)/c")
    expect(readableMath("$\\frac{a}{b}$")).toBe("a/b")
    expect(readableMath("$\\frac{a b}{c-d}$")).toBe("(a b)/(c-d)")
    expect(readableMath("$\\sqrt{x+1}$")).toBe("√(x+1)")
    expect(readableMath("$\\sqrt{x}$")).toBe("√x")
    expect(readableMath("$\\alpha \\le 5^\\circ$")).toBe("α ≤ 5°")
    expect(readableMath("$5^{\\circ}$")).toBe("5°")
    expect(readableMath("$\\Delta T \\approx 3 \\cdot 10^{3}$")).toBe("Δ T ≈ 3 · 10³")
    expect(readableMath("$a \\times b \\pm c \\geq \\infty$")).toBe("a × b ± c ≥ ∞")
    expect(readableMath("$50\\%$")).toBe("50%")
    expect(readableMath("$\\varepsilon\\varphi\\Omega$")).toBe("εφΩ")
  })
  test("delimiters, text commands, spaces", () => {
    expect(readableMath("$$x$$")).toBe("x")
    expect(readableMath("$\\mathrm{HB}$ and $\\mathbf{K}$")).toBe("HB and K")
    expect(readableMath("$\\left( a \\right)$")).toBe("( a )")
    expect(readableMath("$\\left[ a \\right]$")).toBe("[ a ]")
    expect(readableMath("$a\\,b\\;c\\:d\\ e$")).toBe("a b c d e")
    expect(readableMath("$a~b$")).toBe("a b")
  })
  test("a tilde outside a formula stays (approximately)", () => {
    expect(readableMath("~50 °C")).toBe("~50 °C")
  })
  test("inside a formula $x^2 + y_1$ scripts work, \\^10 without braces takes one character", () => {
    expect(readableMath("$x^2 + y_1$")).toBe("x² + y₁")
    expect(readableMath("$2^10$")).toBe("2¹0")
  })
  test("outside $…$ LaTeX is left alone: _ ^ \\ are plain characters", () => {
    expect(readableMath("2^10 bits")).toBe("2^10 bits")
    expect(readableMath("snake_case_name")).toBe("snake_case_name")
    expect(readableMath("file_2.txt")).toBe("file_2.txt")
    expect(readableMath("\\alpha and \\frac{a}{b} x^{2}")).toBe("\\alpha and \\frac{a}{b} x^{2}")
    expect(readableMath("a<sub>1</sub> and $b_2$")).toBe("a₁ and b₂")        // HTML sub/superscripts work everywhere
  })
  test("unknown commands stay as they are", () => {
    expect(readableMath("$\\foo{x}$")).toBe("\\foo{x}")
  })
})

describe("readableMath: nothing is lost", () => {
  test("HTML entities are not decoded, other tags are left alone", () => {
    expect(readableMath("a &amp; b")).toBe("a &amp; b")
    expect(readableMath("&lt;td&gt; <i>x</i>")).toBe("&lt;td&gt; <i>x</i>")
  })
  test("plain text is unchanged", () => {
    expect(readableMath("Каток — 2 шт.")).toBe("Каток — 2 шт.")
    expect(readableMath("")).toBe("")
  })
  test("does not throw on broken markup", () => {
    for (const s of ["\\frac{a", "\\frac{a}{", "x^{", "x_{ab", "\\sqrt{", "<sub>x", "</sub>", "\\", "^", "_", "$", "$\\frac{a$", "$x^{$", "$\\$", "\\text{", "{{{", "\\frac"]) {
      expect(() => readableMath(s)).not.toThrow()
    }
    expect(readableMath("$\\frac{a$")).toBe("\\frac{a")
    expect(readableMath("$ok x^{2$")).toBe("ok x^{2")
    expect(readableMath("<sub>x")).toBe("<sub>x")
  })
})
