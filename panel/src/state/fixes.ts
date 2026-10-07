// The fix list of the Fixes screen: filter, cursor by fix id, next fix "to review".
import type { Fix } from "../bridge/types"
import type { FixFilter, FixesView } from "./store"

export const FILTERS: FixFilter[] = ["all", "review", "applied", "reverted", "not_found"]

const match: Record<FixFilter, (f: Fix) => boolean> = {
  all: () => true,
  review: (f) => f.state === "applied" && f.suggested,
  applied: (f) => f.state === "applied" && !f.suggested,
  reverted: (f) => f.state === "reverted",
  not_found: (f) => f.state === "not_found",
}

export function visibleFixes(v: FixesView): Fix[] {
  return (v.data?.fixes ?? []).filter(match[v.filter])
}

export function cursorIndex(v: FixesView): number {
  return visibleFixes(v).findIndex((f) => f.id === v.cursorId)
}

export function settleCursor(v: FixesView): FixesView {
  const vis = visibleFixes(v)
  if (vis.some((f) => f.id === v.cursorId)) return v
  return { ...v, cursorId: vis[0]?.id ?? null }
}

export function nextReview(v: FixesView): string | null {
  const all = v.data?.fixes ?? []
  const i = all.findIndex((f) => f.id === v.cursorId)
  for (let k = 1; k <= all.length; k++) {
    const f = all[(i + k + all.length) % all.length]
    if (f.state === "applied" && f.suggested) return f.id
  }
  return null
}
