import { For, Show } from "solid-js"
import { Section } from "../components/Section"
import { Span } from "../components/Span"
import { clipContextLine, contextParts, fixColumns, fixCountsLine, fixIcon, fixLegend } from "../fixes-view"
import { oneLine, padEnd, strWidth, truncate } from "../format"
import { CHROME_H } from "../layout"
import { cursorIndex, visibleFixes } from "../state/fixes"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"
import { windowTop } from "./Queue"

const CONTEXT_LINES = 3      // context lines around the fix
// Lines outside the list: name, counters, Section "Fixes" (2), blank, context Section (2), context, "now/was", legend.
const FIXED_ROWS = 1 + 1 + 2 + 1 + 2 + CONTEXT_LINES + 1 + 1
const FILTER_LABEL = { all: "all", review: "to review", applied: "applied", reverted: "printed", not_found: "not found" }

export function FixesScreen(props: { state: AppState; theme: Theme }) {
  const s = () => props.state
  const v = () => s().fixes!
  const t = props.theme
  const width = () => s().size.width - 2
  const cols = () => fixColumns(width())
  const back = () => (v().back === "queue" ? "‹ Queue   " : "‹ Book   ")
  const readOnly = () => (v().data && !v().data!.editable ? 1 : 0)
  const listH = () => Math.max(3, s().size.height - CHROME_H - FIXED_ROWS - readOnly())
  let top = 0
  const vis = () => visibleFixes(v())
  const start = () => (top = windowTop(top, Math.max(0, cursorIndex(v())), listH(), vis().length))
  const cur = () => vis().find((f) => f.id === v().cursorId)
  const color = (icon: string) => (icon === "✓" ? t.ok : icon === "?" ? t.warn : t.muted)
  const pad = () => " ".repeat(strWidth(back()))
  return (
    <box flexDirection="column" flexGrow={1}>
      <text><Span fg={t.muted}>{back()}</Span><strong>{truncate(oneLine(v().book), width() - strWidth(back()))}</strong></text>
      <Show when={v().data} fallback={
        <Show when={v().error} fallback={<text fg={t.muted}>{pad() + "building fix journal…"}</text>}>
          <text><Span fg={t.err}>{truncate(pad() + oneLine(v().error!), width())}</Span></text>
          <text fg={t.muted}>{pad() + "Esc back"}</text>
        </Show>
      }>
        <text fg={t.muted}>{pad() + fixCountsLine(v().data!.fixes.length, v().data!.counts, FILTER_LABEL[v().filter], width() - strWidth(pad()))}</text>
        <Show when={!v().data!.editable}><text fg={t.warn}>{truncate(`read-only: ${oneLine(v().data!.why_not ?? "")}`, width())}</text></Show>
        <Section title="Fixes" width={width()} theme={t} />
        <Show when={vis().length} fallback={<text fg={t.muted}>no fixes in this filter</text>}>
          <For each={vis().slice(start(), start() + listH())}>
            {(f) => {
              const sel = () => f.id === v().cursorId
              const icon = fixIcon(f)
              const ref = f.page ? `${f.scan} p.${f.page}` : f.scan
              const reason = f.state === "not_found" ? `${f.reason ?? ""} · not found`.replace(/^ · /, "") : (f.reason ?? "")
              return (
                <text>
                  <Span fg={sel() ? t.accent : undefined}>{sel() ? "❯ " : "  "}</Span>
                  <Span fg={color(icon)}>{icon + " "}</Span>
                  <span>{padEnd(ref, cols().ref) + " " + padEnd(oneLine(f.was), cols().was) + " " +
                         padEnd(oneLine(f.now) || "(empty)", cols().now)}</span>
                  <Show when={cols().reason}><Span fg={t.muted}>{" " + truncate(reason, cols().reason)}</Span></Show>
                </text>
              )
            }}
          </For>
        </Show>
        <box height={1} />
        <Show when={cur()}>
          {(() => {
            const f = cur()!
            const p = contextParts(f)
            const title = `Context · ${f.page ? `p. ${f.page}` : f.scan}${f.kind ? ` · ${f.kind}` : ""}` +
              (cols().reason ? "" : f.reason ? ` · ${f.reason}` : "")
            // The line with the fix plus its neighbours: one line above and below, CONTEXT_LINES at most.
            const bl = p.before.split("\n"), al = p.after.split("\n")
            const pre = bl.slice(-2, -1).map(oneLine), post = al.slice(1).map(oneLine).filter(Boolean)
            const main = clipContextLine(bl[bl.length - 1], oneLine(p.cur), al[0], width())
            const lines = [...pre, null, ...post].slice(0, CONTEXT_LINES)
            return (
              <box flexDirection="column">
                <Section title={truncate(title, width())} width={width()} theme={t} />
                <For each={lines}>
                  {(ln) => ln === null ? (
                    <text>
                      <span>{main.before}</span><Span fg={t.warn}><strong>{main.mid}</strong></Span><span>{main.after}</span>
                    </text>
                  ) : <text>{truncate(ln, width())}</text>}
                </For>
                <text fg={t.muted}>{truncate(`${p.otherLabel}: ${oneLine(p.other) || "(empty)"}`, width())}</text>
              </box>
            )
          })()}
        </Show>
        <text fg={t.muted}>{fixLegend(width())}</text>
      </Show>
    </box>
  )
}
