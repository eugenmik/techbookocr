import { For, Show } from "solid-js"
import type { StageRow } from "../bridge/types"
import { bar, fmtDuration, padEnd, padStart, strWidth } from "../format"
import type { Theme } from "../theme"
import { Span } from "./Span"

const ICON = { done: "✓", running: "▸", pending: "·" } as const
const RIGHT_MIN = 8   // fits "s/pp" and "18.1"; the progress of a big book (3155/31550) widens the column

const rightText = (r: StageRow): string =>
  r.status === "running" && r.progress
    ? `${r.progress[0]}/${r.progress[1]}`
    : r.s_per_page != null ? r.s_per_page.toFixed(1) : "—"

/** Stage table: icon, name, time, s/pp or x/y; the running stage has an ETA (and a bar in the wide view). */
export function StageTable(props: { stages: StageRow[]; theme: Theme; wide: boolean }) {
  const color = (st: StageRow["status"]) =>
    st === "done" ? props.theme.ok : st === "running" ? props.theme.accent : props.theme.muted
  // The last column is as wide as its longest value, so x/y is never truncated
  const rw = () => Math.max(RIGHT_MIN, ...props.stages.map((r) => strWidth(rightText(r))))
  return (
    <box flexDirection="column">
      <text><Span fg={props.theme.muted}>{`  ${padEnd("Stage", 10)} ${padStart("Time", 6)}  ${padStart("s/pp", rw())}`}</Span></text>
      <For each={props.stages}>
        {(r) => {
          const right = rightText(r)
          return (
            <box flexDirection="column">
              <text>
                <Span fg={color(r.status)}>{ICON[r.status] + " "}</Span>
                <span>{`${padEnd(r.stage, 10)} ${padStart(r.seconds != null ? fmtDuration(r.seconds) : "—", 6)}  ${padStart(right, rw())}`}</span>
                <Show when={props.wide && r.status === "running" && r.progress}>
                  <Span fg={props.theme.accent}>{"  " + bar(r.progress![0], r.progress![1], 10)}</Span>
                </Show>
              </text>
              <Show when={r.status === "running" && r.eta_s != null}>
                <text><Span fg={props.theme.muted}>{padStart(`ETA ${fmtDuration(r.eta_s)}`, 21 + rw())}</Span></text>
              </Show>
            </box>
          )
        }}
      </For>
    </box>
  )
}
