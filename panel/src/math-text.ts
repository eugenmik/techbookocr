// Readable form of formula markup for the Fixes screen: <sub>/<sup> and LaTeX → Unicode. Display only:
// the book and the fix journal do not change. HTML entities are not decoded, so a fix "& → &amp;" stays visible.

const SUB: Record<string, string> = {
  "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
  "+": "₊", "−": "₋", "=": "₌", "(": "₍", ")": "₎",
  a: "ₐ", e: "ₑ", h: "ₕ", i: "ᵢ", j: "ⱼ", k: "ₖ", l: "ₗ", m: "ₘ", n: "ₙ", o: "ₒ", p: "ₚ", r: "ᵣ", s: "ₛ", t: "ₜ",
  u: "ᵤ", v: "ᵥ", x: "ₓ",
}
const SUP: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
  "+": "⁺", "−": "⁻", "=": "⁼", "(": "⁽", ")": "⁾", "°": "°",
  a: "ᵃ", b: "ᵇ", c: "ᶜ", d: "ᵈ", e: "ᵉ", f: "ᶠ", g: "ᵍ", h: "ʰ", i: "ⁱ", j: "ʲ", k: "ᵏ", l: "ˡ", m: "ᵐ", n: "ⁿ",
  o: "ᵒ", p: "ᵖ", r: "ʳ", s: "ˢ", t: "ᵗ", u: "ᵘ", v: "ᵛ", w: "ʷ", x: "ˣ", y: "ʸ", z: "ᶻ",
  A: "ᴬ", B: "ᴮ", D: "ᴰ", E: "ᴱ", G: "ᴳ", H: "ᴴ", I: "ᴵ", J: "ᴶ", K: "ᴷ", L: "ᴸ", M: "ᴹ", N: "ᴺ", O: "ᴼ",
  P: "ᴾ", R: "ᴿ", T: "ᵀ", U: "ᵁ", V: "ⱽ", W: "ᵂ",
}

const SYMBOLS: Record<string, string> = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", zeta: "ζ", eta: "η", theta: "θ", iota: "ι",
  kappa: "κ", lambda: "λ", mu: "μ", nu: "ν", xi: "ξ", pi: "π", rho: "ρ", sigma: "σ", tau: "τ", upsilon: "υ",
  phi: "φ", chi: "χ", psi: "ψ", omega: "ω", varepsilon: "ε", varphi: "φ",
  Gamma: "Γ", Delta: "Δ", Theta: "Θ", Lambda: "Λ", Xi: "Ξ", Pi: "Π", Sigma: "Σ", Phi: "Φ", Psi: "Ψ", Omega: "Ω",
  cdot: "·", times: "×", le: "≤", leq: "≤", ge: "≥", geq: "≥", pm: "±", approx: "≈", infty: "∞",
  circ: "°", degree: "°",
}
const TEXT_CMDS = new Set(["text", "mathrm", "mathbf", "mathit", "textbf", "textit", "operatorname"])
const SPACE_CMDS = new Set([",", ";", ":", " "])

/** Wrap a fraction/root part in parentheses if it holds a space or an operator. */
const needsParens = (s: string) => /[\s+\-−*/×·±=<>≤≥]/.test(s)

/** Contents of `{…}` starting at `i` (where `{` is): [text, position after `}`], or null if the braces do not match. */
function group(s: string, i: number): [string, number] | null {
  if (s[i] !== "{") return null
  let depth = 0
  for (let j = i; j < s.length; j++) {
    if (s[j] === "{") depth++
    else if (s[j] === "}" && --depth === 0) return [s.slice(i + 1, j), j + 1]
  }
  return null
}

/** Superscript/subscript: Unicode if every character has such a form; otherwise `_w`, `^{cr}`. */
function script(kind: "_" | "^", body: string): string {
  if (!body) return ""
  const table = kind === "_" ? SUB : SUP
  const chars = [...body.replace(/-/g, "−")]
  if (chars.every((c) => table[c] !== undefined)) return chars.map((c) => table[c]).join("")
  return chars.length === 1 ? kind + body : `${kind}{${body}}`
}

const TAG = /^<(sub|sup)>/i

/** `math`: inside `$…$`, where LaTeX is parsed too; outside a formula only <sub>/<sup>, and `_ ^ \` stay plain characters. */
function render(s: string, math: boolean): string {
  let out = ""
  let i = 0
  while (i < s.length) {
    const c = s[i]
    if (c === "<") {
      const m = TAG.exec(s.slice(i, i + 6))
      if (m) {
        const close = s.toLowerCase().indexOf(`</${m[1].toLowerCase()}>`, i + m[0].length)
        if (close !== -1) {
          out += script(m[1].toLowerCase() === "sub" ? "_" : "^", render(s.slice(i + m[0].length, close), math))
          i = close + m[1].length + 3
          continue
        }
      }
    } else if (!math) {
      // outside a formula everything else is literal
    } else if (c === "^" || c === "_") {
      const kind = c
      let body: string | null = null
      let next = i + 1
      if (s[next] === "{") {
        const g = group(s, next)
        if (!g) return out + s.slice(i)                       // braces do not match: the rest as is
        body = render(g[0], true)
        next = g[1]
      } else if (s[next] === "\\") {
        const cm = /^\\([A-Za-z]+)/.exec(s.slice(next))
        if (cm && SYMBOLS[cm[1]] !== undefined) { body = SYMBOLS[cm[1]]; next += cm[0].length }
      } else if (next < s.length && !/\s/.test(s[next]) && !"^_{}$<".includes(s[next])) {
        body = s[next]
        next++
      }
      if (body !== null) { out += script(kind, body); i = next; continue }
    } else if (c === "\\") {
      const cm = /^\\([A-Za-z]+)/.exec(s.slice(i, i + 40))
      const name = cm ? cm[1] : s[i + 1]
      const end = i + 1 + (cm ? cm[1].length : name ? 1 : 0)
      if (name !== undefined) {
        if (SYMBOLS[name] !== undefined && cm) { out += SYMBOLS[name]; i = end; continue }
        if (SPACE_CMDS.has(name)) { out += " "; i = end; continue }
        if (name === "%") { out += "%"; i = end; continue }
        if (name === "left" || name === "right") {
          i = end
          if (s[i] === ".") i++                              // \left. is an invisible delimiter
          continue
        }
        if (TEXT_CMDS.has(name)) {
          const g = group(s, end)
          if (!g) return out + s.slice(i)
          out += render(g[0], true)
          i = g[1]
          continue
        }
        if (name === "frac") {
          const a = group(s, end)
          const b = a && group(s, a[1])
          if (!a || !b) return out + s.slice(i)
          const p = render(a[0], true), q = render(b[0], true)
          out += (needsParens(p) ? `(${p})` : p) + "/" + (needsParens(q) ? `(${q})` : q)
          i = b[1]
          continue
        }
        if (name === "sqrt") {
          const a = group(s, end)
          if (!a) return out + s.slice(i)
          const p = render(a[0], true)
          out += "√" + (needsParens(p) ? `(${p})` : p)
          i = a[1]
          continue
        }
      }
    }
    out += c
    i++
  }
  return out
}

/** Formulas `$…$`/`$$…$$` lose the dollar signs and get LaTeX parsing (`~` inside is a space); text between them gets only HTML sub/superscripts. */
function renderAll(s: string): string {
  let out = ""
  let last = 0
  for (const m of s.matchAll(/\$\$([^$]*)\$\$|\$([^$]*)\$/g)) {
    out += render(s.slice(last, m.index), false) + render((m[1] ?? m[2] ?? "").replace(/~/g, " "), true)
    last = m.index! + m[0].length
  }
  return out + render(s.slice(last), false)
}

/** Readable form of a string with formula markup; never throws. */
export function readableMath(s: string): string {
  try {
    return renderAll(s)
  } catch {
    return s
  }
}
