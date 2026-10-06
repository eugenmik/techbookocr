import { Span } from "./Span"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"
import { fmtDuration, fmtGB, fmtInt, padEnd, strWidth, truncate } from "../format"

function daemonPart(s: AppState): { icon: string; text: string; color?: (t: Theme) => string | undefined } {
  const d = s.snap?.daemon
  if (!d) return { icon: "…", text: "connecting" }
  if (!d.alive) return { icon: "○", text: "stopped", color: (t) => t.muted }
  const stage = s.snap?.current?.stage
  const model = s.snap?.model?.key
  const extra = [stage, model].filter(Boolean).join(" · ")
  if (d.state === "paused") return { icon: "◌", text: `paused${extra ? "  " + extra : ""}`, color: (t) => t.warn }
  return { icon: "●", text: `${d.state}${extra ? "  " + extra : ""}`, color: (t) => t.ok }
}

/** Fixed-width column: text is truncated so that ≥ 2 spaces remain before the next column. */
const col = (text: string, w: number) => padEnd(truncate(text, Math.max(1, w - 2)), w)

const TITLE = "techbookocr"

export function StatusStrip(props: { state: AppState; theme: Theme; width: number }) {
  const s = () => props.state
  const root = () => s().snap?.root ?? (s().bridge.kind === "ready" ? (s().bridge as any).root : "")
  const queue = () => {
    const f = s().snap?.forecast
    if (!f) return "Queue —"
    const unknown = f.unknown_scans > 0 && !f.scans              // scans unknown: "≈0s" would be a lie
    const eta = unknown ? " · —" : f.seconds != null ? ` · ≈${fmtDuration(f.seconds)}` : ""
    const pp = f.scans ? ` · ≈${fmtInt(f.scans)} pp` : ""
    return `Queue ${f.queued_books} books${pp}${eta}`
  }
  const gpu = () => {
    const g = s().snap?.gpu
    return g ? `GPU ${fmtGB(g.used_mib)}/${fmtGB(g.total_mib)} GB · ${g.util}%` : "GPU —"
  }
  const hint = () => (s().snap && !s().snap!.daemon.alive && (s().snap!.counts.queued ?? 0) > 0 ? "  → press d to start" : "")
  const gpuW = () => Math.max(0, props.width - 2 - 2 * third())          // GPU column: the line itself and the hint share its width
  const gpuText = () => truncate(gpu(), gpuW())
  const d = () => daemonPart(s())
  const third = () => Math.floor((props.width - 2) / 3)
  return (
    <box flexDirection="column">
      <text>
        <strong>{TITLE}</strong>
        <Span fg={props.theme.muted}>{" ".repeat(Math.max(2, props.width - TITLE.length - 2 - strWidth(truncate(root(), props.width - TITLE.length - 5))))}{truncate(root(), props.width - TITLE.length - 5)}</Span>
      </text>
      <text>
        <Span fg={d().color?.(props.theme)}>{d().icon} </Span>
        <span>{col(d().text, third() - 2)}</span>
        <span>{col(queue(), third())}</span>
        <span>{gpuText()}</span>
        <Span fg={props.theme.warn}>{truncate(hint(), Math.max(0, gpuW() - strWidth(gpuText())))}</Span>
      </text>
    </box>
  )
}
