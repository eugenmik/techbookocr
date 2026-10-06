// Text by on-screen width (not string length): Cyrillic is 1 column, CJK and emoji are 2,
// combining marks are 0. Truncation is on grapheme boundaries.
const graphemes = new Intl.Segmenter(undefined, { granularity: "grapheme" })

export const strWidth = (s: string): number => Bun.stringWidth(s)

/** A line from raw library text (errors, events): control characters and newlines → space, whitespace collapsed. */
export const oneLine = (s: string): string => s.replace(/[\u0000-\u001f\u007f-\u009f\s]+/g, " ").trim()

export function truncate(s: string, max: number): string {
  if (max <= 0) return ""
  if (strWidth(s) <= max) return s
  let out = ""
  let w = 0
  for (const { segment } of graphemes.segment(s)) {
    const cw = strWidth(segment)
    if (w + cw > max - 1) break
    out += segment
    w += cw
  }
  return out + "…"
}

export function padEnd(s: string, n: number): string {
  const t = truncate(s, n)
  return t + " ".repeat(Math.max(0, n - strWidth(t)))
}

export function padStart(s: string, n: number): string {
  const t = truncate(s, n)
  return " ".repeat(Math.max(0, n - strWidth(t))) + t
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return "—"
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s}s`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h${String(m % 60).padStart(2, "0")}m`
  return `${Math.floor(h / 24)}d ${h % 24}h`
}

export const fmtInt = (n: number): string => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ")

export const fmtGB = (mib: number): string => (mib / 1024).toFixed(1)

export function bar(done: number, total: number, width: number): string {
  const f = total > 0 ? Math.min(width, Math.floor((width * done) / total)) : 0
  return "█".repeat(f) + "░".repeat(width - f)
}

const SPARK = "▁▂▃▄▅▆▇█"

export function sparkline(values: number[], width: number, max?: number): string {
  const vs = values.slice(-width)
  if (!vs.length) return ""
  const top = max ?? Math.max(...vs, 1e-9)
  return vs.map((v) => SPARK[Math.max(0, Math.min(7, Math.round((v / top) * 7)))]).join("")
}
