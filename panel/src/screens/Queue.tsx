import { For, Show } from "solid-js"
import type { BookItem } from "../bridge/types"
import { BookCard } from "../components/BookCard"
import { Span } from "../components/Span"
import { Section } from "../components/Section"
import { bar, oneLine, padEnd, padStart, truncate } from "../format"
import { COL, GUTTER, queueLayout } from "../layout"
import { visibleBooks } from "../state/select"
import type { AppState } from "../state/store"
import { STATUS_ICON, statusColor, type Theme } from "../theme"

export function bookRowText(b: BookItem, nameW: number, selected: boolean, marked: boolean) {
  const ptr = (selected ? "❯" : " ") + (marked ? "●" : " ")
  const word = b.status === "processing" ? (b.stage ?? "processing") : b.status
  let detail = ""
  if (b.status === "processing" && b.progress && b.progress[1] > 0)
    detail = `${bar(b.progress[0], b.progress[1], 10)} ${padStart(`${Math.floor((100 * b.progress[0]) / b.progress[1])}%`, 4)}`
  else if (b.status === "failed") detail = oneLine(b.error ?? "") || "failed"
  else if (b.scans != null) detail = `${b.scans} pp`
  return {
    ptr,
    name: padEnd(b.name, nameW),
    state: padEnd(`${STATUS_ICON[b.status] ?? "?"} ${word}`, COL.state),
    detail: padEnd(detail, COL.detail),
    prio: padStart(b.priority ? `p${b.priority}` : "", COL.prio),
  }
}

/** Top of the list window: moves only when the cursor leaves the window. */
export function windowTop(prev: number, cursor: number, h: number, n: number): number {
  const top = Math.max(cursor - h + 1, Math.min(prev, cursor))
  return Math.max(0, Math.min(top, Math.max(0, n - h)))
}

export function QueueScreen(props: { state: AppState; theme: Theme }) {
  const s = () => props.state
  const L = () => queueLayout(s().size.width, s().size.height)
  const books = () => visibleBooks(s())
  let top = 0                                   // local window state, not in the store
  const start = () => (top = windowTop(top, s().cursor, L().tableH, books().length))
  const rows = () => books().slice(start(), start() + L().tableH).map((b, i) => ({ b, i: start() + i }))
  const title = () => {
    const parts = [`${books().length}`]
    if (s().marks.length) parts.push(`${s().marks.length} marked`)
    if (s().filter.text || s().filter.active) parts.push(`filter "${s().filter.text}"${s().filter.active ? "▏" : ""}`)
    return parts.join(" · ")
  }
  const events = () => (s().snap?.events ?? []).slice(-L().eventsH)
  const t = props.theme
  return (
    <box flexDirection="row" flexGrow={1} paddingTop={1}>
      <box flexDirection="column" width={L().leftW}>
        <text><strong>Books</strong><Span fg={t.muted}>{`  ${title()}`}</Span></text>
        <box height={1} />
        <box flexDirection="column" height={L().tableH}>
          <Show when={books().length} fallback={<text><Span fg={t.muted}>No books yet · press a to add</Span></text>}>
            <For each={rows()}>
              {({ b, i }) => {
                const sel = i === s().cursor
                const p = bookRowText(b, L().nameW, sel, s().marks.includes(b.name))
                return (
                  <text>
                    <Span inverse={sel} fg={t.accent}>{p.ptr + " "}</Span>
                    {sel ? <strong><Span inverse>{p.name}</Span></strong> : <span>{p.name}</span>}
                    <Span inverse={sel}>{"  "}</Span>
                    <Span inverse={sel} fg={statusColor(t, b.status)}>{p.state}</Span>
                    <Span inverse={sel}>{"  "}</Span>
                    <Span inverse={sel} fg={b.status === "failed" ? t.err : b.status === "processing" ? t.accent : t.muted}>{p.detail}</Span>
                    <Span inverse={sel} fg={t.muted}>{p.prio}</Span>
                  </text>
                )
              }}
            </For>
          </Show>
        </box>
        <box flexGrow={1} />
        <Section title="Recent events" width={L().leftW} theme={t} />
        <For each={events()}>
          {(e) => (
            <text>
              <Span fg={t.muted}>{e.ts.slice(11, 16) + "  "}</Span>
              <Span fg={e.level === "error" ? t.err : e.level === "warn" ? t.warn : undefined}>
                {truncate(`${e.book ? truncate(oneLine(e.book), 16) + "  " : ""}${oneLine(e.message)}`, L().leftW - 7)}
              </Span>
            </text>
          )}
        </For>
      </box>
      <Show when={L().cardW > 0}>
        <box width={GUTTER} />
        <BookCard state={s()} theme={t} width={L().cardW} />
      </Show>
    </box>
  )
}
