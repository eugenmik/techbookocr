import { Show } from "solid-js"
import { fixSummaryLine } from "../fixes-view"
import { oneLine, truncate } from "../format"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"
import { Section } from "./Section"
import { Span } from "./Span"
import { StageTable } from "./StageTable"

export function bookInfoLine(i: { pages: number | null; scans: number | null; kind: string; lang: string | null; mode: string | null }): string {
  const pp = i.pages ?? i.scans
  return [pp != null ? `${pp} pp` : null, i.kind, i.lang, i.mode].filter(Boolean).join(" · ")
}

/** Card of the selected book to the right of the queue (width ≥ 110). */
export function BookCard(props: { state: AppState; theme: Theme; width: number }) {
  const d = () => (props.state.book && props.state.book.info.name === props.state.bookName ? props.state.book : null)
  return (
    <box flexDirection="column" width={props.width}>
      <Show when={d()} fallback={<text><Span fg={props.theme.muted}>{props.state.bookName ? "loading…" : ""}</Span></text>}>
        <Section title={truncate(d()!.info.name, props.width)} width={props.width} theme={props.theme} />
        <text><Span fg={props.theme.muted}>{bookInfoLine(d()!.info)}</Span></text>
        <box height={1} />
        <Show when={d()!.stages.length} fallback={<text><Span fg={props.theme.muted}>not started yet</Span></text>}>
          <StageTable stages={d()!.stages} theme={props.theme} wide={false} />
        </Show>
        <box height={1} />
        <text>
          <Span fg={props.theme.muted}>{"Quality  "}</Span>
          <Span fg={d()!.issues.length ? props.theme.warn : props.theme.ok}>
            {d()!.issues.length ? `${d()!.issues.length} issue${d()!.issues.length === 1 ? "" : "s"}` : "no issues"}
          </Span>
        </text>
        <Show when={fixSummaryLine(d()!.fixes)}>
          <text><Span fg={d()!.fixes?.suggested ? props.theme.warn : props.theme.muted}>{fixSummaryLine(d()!.fixes)!}</Span></text>
        </Show>
        <Show when={d()!.info.error}>
          <text><Span fg={props.theme.err}>{truncate(`✗ ${oneLine(d()!.info.error!)}`, props.width)}</Span></text>
        </Show>
      </Show>
    </box>
  )
}
