// Panel palette: muted, accent, ok/warn/err. With NO_COLOR or TERM=dumb there is no color
// (only bold/dim via <strong>; dimming is not used), state is conveyed by icons.
export interface Theme {
  color: boolean
  muted?: string
  accent?: string
  ok?: string
  warn?: string
  err?: string
}

export function makeTheme(env: Record<string, string | undefined> = process.env): Theme {
  const color = !env.NO_COLOR && env.TERM !== "dumb"
  if (!color) return { color }
  return { color, muted: "#8a8a8a", accent: "#5fafd7", ok: "#87af5f", warn: "#d7af5f", err: "#d75f5f" }
}

export const STATUS_ICON: Record<string, string> = {
  processing: "▸", queued: "·", done: "✓", failed: "✗", skipped: "–",
}

export function statusColor(t: Theme, status: string): string | undefined {
  switch (status) {
    case "processing": return t.accent
    case "done": return t.ok
    case "failed": return t.err
    case "queued":
    case "skipped": return t.muted
    default: return undefined
  }
}
