// Telemetry since the panel was opened: a point per snapshot (once a second).
// Rate is the growth of the current stage's "done" over the RATE_WINDOW_MS window; a change of book or stage resets the window.
import type { Snapshot } from "../bridge/types"

export const HISTORY_MAX = 1800
export const RATE_WINDOW_MS = 600_000

export interface History {
  gpuMem: number[]; gpuUtil: number[]; rate: number[]; rateUnit: string
  progKey: string | null; samples: { at: number; done: number }[]
}

export const emptyHistory = (): History =>
  ({ gpuMem: [], gpuUtil: [], rate: [], rateUnit: "pp/min", progKey: null, samples: [] })

const push = (xs: number[], v: number) => [...xs, v].slice(-HISTORY_MAX)

export function pushSnapshot(h: History, snap: Snapshot, now: number): History {
  const g = snap.gpu
  const gpuMem = push(h.gpuMem, g ? (g.used_mib / Math.max(1, g.total_mib)) * 100 : 0)
  const gpuUtil = push(h.gpuUtil, g ? g.util : 0)
  const c = snap.current
  const key = c && c.progress ? `${c.name}/${c.stage}` : null
  let samples = key && key === h.progKey ? h.samples : []
  if (c && c.progress) samples = [...samples, { at: now, done: c.progress[0] }].filter((p) => now - p.at <= RATE_WINDOW_MS)
  let rate = 0
  if (samples.length >= 2) {
    const a = samples[0], b = samples[samples.length - 1]
    const min = (b.at - a.at) / 60_000
    rate = min > 0 ? Math.max(0, (b.done - a.done) / min) : 0
  }
  const rateUnit = c?.stage === "layout" ? "pp/min" : c ? "blocks/min" : h.rateUnit
  return { gpuMem, gpuUtil, rate: push(h.rate, rate), rateUnit, progKey: key, samples }
}
