import { For, Show } from "solid-js"
import type { FieldValue, SettingField } from "../bridge/types"
import { Span } from "../components/Span"
import { oneLine, padEnd, strWidth, truncate } from "../format"
import { fieldId } from "../state/select"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"
import { windowTop } from "./Queue"

const LABEL_W = 20
/** Rows around the list: 7 rows of app frame + top padding, header, error row. */
const CHROME_H = 7 + 3

export function displayValue(f: SettingField, v: FieldValue, selected: boolean, editing: string | null): string {
  if (selected && editing !== null) return editing + "▏"
  const text = v === null ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : oneLine(String(v))
  const cyclable = f.kind === "bool" || f.choices.length > 0
  return selected && cyclable ? `‹ ${text} ›` : text
}

type Line =
  | { kind: "head"; section: string }
  | { kind: "field"; f: SettingField; i: number }
  | { kind: "comment"; text: string; i: number }

export function SettingsScreen(props: { state: AppState; theme: Theme }) {
  const s = () => props.state
  const t = props.theme
  const inner = () => s().size.width - 2
  const st = () => s().settings
  // Flat list of rows: section header, field, rows of its comment.
  // Rows are needed so the scroll window is computed from the real height.
  const lines = () => {
    const out: Line[] = []
    const seen = new Set<string>()
    for (const sec of st()?.data.fields.map((f) => f.section) ?? []) {
      if (seen.has(sec)) continue
      seen.add(sec)
      out.push({ kind: "head", section: sec })
      st()!.data.fields.forEach((f, i) => {
        if (f.section !== sec) return
        out.push({ kind: "field", f, i })
        if (f.comment) for (const c of f.comment.split("\n")) if (oneLine(c)) out.push({ kind: "comment", text: oneLine(c), i })
      })
    }
    return out
  }
  const h = () => Math.max(3, s().size.height - CHROME_H)
  let top = 0                                   // local scroll window, not in the store
  const visible = () => {
    const all = lines()
    const cur = st()?.cursor ?? 0
    const idx = all.map((l, n) => (l.kind !== "head" && l.i === cur ? n : -1)).filter((n) => n >= 0)
    if (!idx.length) return all.slice(top, top + h())
    const fieldIdx = idx[0]
    const headIdx = all.findLastIndex((l, n) => l.kind === "head" && n < fieldIdx)
    top = windowTop(top, idx[idx.length - 1], h(), all.length)
    if (top > fieldIdx) top = fieldIdx
    if (top <= headIdx) return all.slice(top, top + h())
    // The section header scrolled out of the window: it stays sticky as the first row, the field gets h-1 rows.
    top = windowTop(top, idx[idx.length - 1], h() - 1, all.length)
    if (top > fieldIdx) top = fieldIdx
    if (top <= headIdx) return all.slice(top, top + h())
    return [all[headIdx], ...all.slice(top, top + h() - 1)]
  }
  /** Tail of the line, at most w wide: while editing the caret at the end stays visible. */
const tail = (x: string, w: number) => {
  let out = ""
  for (const ch of [...x].reverse()) { if (strWidth(ch + out) > w) break; out = ch + out }
  return out
}
  const dirty = () => Object.keys(st()?.draft ?? {}).length > 0
  return (
    <Show when={st()} fallback={<text fg={t.muted}>loading settings…</text>}>
      <box flexDirection="column" flexGrow={1} paddingTop={1}>
        <text>
          <strong>Settings</strong>
          <Span fg={t.muted}>{"  " + truncate(oneLine(st()!.data.path), inner() - 24)}</Span>
          <Span fg={t.warn}>{dirty() ? "  ● unsaved" : ""}</Span>
        </text>
        <text fg={t.err}>{truncate(oneLine(st()!.error ?? ""), inner())}</text>
        <For each={visible()}>
          {(l) => {
            if (l.kind === "head") {
              const title = `[${l.section}] `
              return <text><strong>{title}</strong><Span fg={t.muted}>{"─".repeat(Math.max(0, inner() - title.length))}</Span></text>
            }
            if (l.kind === "comment")
              return <text><Span fg={t.muted}>{"  " + " ".repeat(LABEL_W) + truncate(l.text, inner() - LABEL_W - 2)}</Span></text>
            const f = l.f
            const sel = l.i === st()!.cursor
            const id = fieldId(f)
            const changed = id in st()!.draft
            const v = changed ? st()!.draft[id] : f.value
            const editing = sel && st()!.editing !== null
            const room = inner() - LABEL_W - 6
            const shown = displayValue(f, v, sel, sel ? st()!.editing : null)
            const val = editing && strWidth(shown) > room ? "…" + tail(shown, room - 1) : truncate(shown, room)
            return (
              <text>
                <Span fg={t.accent}>{sel ? "❯ " : "  "}</Span>
                <Span fg={t.muted}>{padEnd(f.key, LABEL_W)}</Span>
                {sel ? <strong><Span fg={t.accent}>{val}</Span></strong> : <span>{val}</span>}
                <Span fg={t.warn}>{changed ? "  ●" : ""}</Span>
              </text>
            )
          }}
        </For>
      </box>
    </Show>
  )
}
