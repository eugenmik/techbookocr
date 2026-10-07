// Fix display: state icon, simplified context markup, column widths, summary.
import type { Fix, FixSummary } from "./bridge/types"
import { strWidth, truncate } from "./format"

const graphemes = new Intl.Segmenter(undefined, { granularity: "grapheme" })

/** The tail of a string at most `max` columns wide; the cut-off start is replaced with "…". */
export function truncateStart(s: string, max: number): string {
  if (max <= 0) return ""
  if (strWidth(s) <= max) return s
  const segs = [...graphemes.segment(s)].map((x) => x.segment)
  let out = ""
  let w = 0
  for (let i = segs.length - 1; i >= 0; i--) {
    const cw = strWidth(segs[i])
    if (w + cw > max - 1) break
    out = segs[i] + out
    w += cw
  }
  return "…" + out
}

/**
 * A "before ⟦fix⟧ after" context line no wider than `width` columns: the neighbouring fragments
 * shrink first (the start is cut on the left, the end on the right), the bracketed part stays visible.
 */
export function clipContextLine(before: string, cur: string, after: string, width: number) {
  const mid = truncate("⟦" + cur + "⟧", width)
  const rest = Math.max(0, width - strWidth(mid))
  const a = strWidth(before), b = strWidth(after)
  const beforeBudget = Math.min(a, Math.max(Math.floor(rest / 2), rest - b))
  const afterBudget = Math.min(b, rest - beforeBudget)
  return { before: truncateStart(before, beforeBudget), mid, after: truncate(after, afterBudget) }
}

/** Legend; a short form on a narrow screen. */
export function fixLegend(width: number): string {
  const full = "✓ applied   ↶ printed text kept   ? rule suggests reverting   · not found in book.md"
  const short = "✓ applied ↶ printed ? review · not found"
  return truncate(strWidth(full) <= width ? full : short, width)
}

/** The counters and filter line: the full form if it fits, otherwise with icons. */
export function fixCountsLine(total: number, c: { applied: number; reverted: number; suggested: number; not_found: number },
                              filter: string, width: number): string {
  const full = `Fixes ${total} · applied ${c.applied} · printed ${c.reverted} · to review ${c.suggested}` +
    ` · not found ${c.not_found}   filter: ${filter}`
  const compact = `Fixes ${total} · ✓${c.applied} ↶${c.reverted} ?${c.suggested} ·${c.not_found} · ${filter}`
  return truncate(strWidth(full) <= width ? full : compact, width)
}

/** The second line of the Book header: the fullest form of the fix summary that fits in `width`. */
export function bookSubline(pad: string, info: string, added: string, sum: FixSummary | null | undefined, width: number): string {
  const full = fixSummaryLine(sum)
  const shortSum = sum && sum.total ? `Fixes ${sum.total} · f` : null
  const variants = [
    pad + info + `  ·  added ${added}` + (full ? `  ·  ${full}` : ""),
    shortSum && pad + info + `  ·  added ${added}  ·  ${shortSum}`,
    shortSum && pad + info + `  ·  ${shortSum}`,
    pad + info + `  ·  added ${added}`,
  ]
  for (const v of variants) if (v && strWidth(v) <= width) return v
  return truncate(variants[shortSum ? 2 : 3]!, width)
}

export function fixIcon(f: Fix): "✓" | "↶" | "?" | "·" {
  if (f.state === "not_found") return "·"
  if (f.state === "reverted") return "↶"
  return f.suggested ? "?" : "✓"
}

/** Table → "a │ b", rows on new lines; tags other than <sub>/<sup> are removed. For display only. */
export function simplifyMarkup(s: string): string {
  return s
    .replace(/<\/t[dh]>\s*<t[dh][^>]*>/g, " │ ")
    .replace(/<\/tr>\s*/g, "\n")
    .replace(/<br\s*\/?>/g, " ")
    .replace(/<(?!\/?(?:sub|sup)>)[^>]*>/g, "")
}

export function contextParts(f: Fix) {
  let before = f.before
  const lt = before.indexOf("<"), gt = before.indexOf(">")
  if (gt !== -1 && (lt === -1 || gt < lt)) before = before.slice(gt + 1)      // the context started in the middle of a tag
  let after = f.after
  const alt = after.lastIndexOf("<"), agt = after.lastIndexOf(">")
  if (alt > agt) after = after.slice(0, alt)                                  // and ended in the middle of a tag
  const applied = f.state === "applied"
  return { before: simplifyMarkup(before), cur: applied ? f.now : f.was, after: simplifyMarkup(after),
           other: applied ? f.was : f.now, otherLabel: (applied ? "was" : "now") as "was" | "now" }
}

export function fixColumns(width: number) {
  const ref = 13, icon = 4
  const reason = width >= 100 ? 26 : 0
  const free = width - icon - ref - reason - 3
  const half = Math.max(8, Math.floor(free / 2))
  return { ref, was: half, now: free - half, reason }
}

export function fixSummaryLine(sum: FixSummary | null | undefined): string | null {
  if (!sum || !sum.total) return null
  // suggested 0: no "?", but the book may never have been opened, so not "reviewed" but "nothing to review"
  const tail = sum.suggested == null ? "not reviewed" : sum.suggested ? `${sum.suggested} to review` : "nothing to review"
  return `Fixes ${sum.total} · ${tail} · f`
}
