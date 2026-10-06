// Queue screen layout from the window size. Chrome (metrics row, tabs, lines, footer) is CHROME_H rows.
export const MIN_W = 80
export const MIN_H = 24
export const CARD_MIN_W = 110
export const CARD_W = 40
export const GUTTER = 4
export const CHROME_H = 7          // 2 metrics rows + blank + tabs + line; line + footer
export const COL = { ptr: 2, state: 13, detail: 18, prio: 4 } as const

export interface QueueLayout { leftW: number; cardW: number; tableH: number; eventsH: number; nameW: number }

export function queueLayout(w: number, h: number): QueueLayout {
  const inner = w - 2                                     // 1-column padding on each side
  const cardW = w >= CARD_MIN_W ? CARD_W : 0
  const leftW = cardW ? inner - cardW - GUTTER : inner
  const eventsH = h >= 30 ? 6 : 3
  const body = h - CHROME_H
  const tableH = Math.max(3, body - 2 - 1 - (2 + eventsH))  // header+blank, blank, events header+line
  const nameW = Math.max(10, leftW - COL.ptr - COL.state - COL.detail - COL.prio - 6)
  return { leftW, cardW, tableH, eventsH, nameW }
}
