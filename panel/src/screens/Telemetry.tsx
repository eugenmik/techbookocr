import { For } from "solid-js"
import { Section } from "../components/Section"
import { Span } from "../components/Span"
import { fmtDuration, fmtGB, oneLine, padEnd, sparkline, truncate } from "../format"
import { CHROME_H } from "../layout"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"

export const LABEL_W = 12
export const VALUE_W = 30
const SECTION_H = 2           // header + line
const METRIC_ROWS = 3         // GPU memory, GPU load, Throughput
const MODEL_ROWS = 1
const PAD_TOP = 1
const GAP = 1                 // blank line before the log
const FIXED_H = PAD_TOP + SECTION_H + METRIC_ROWS + MODEL_ROWS + GAP + SECTION_H
const MIN_LOG_H = 3

export function TelemetryScreen(props: { state: AppState; theme: Theme }) {
  const s = () => props.state
  const t = props.theme
  const inner = () => s().size.width - 2
  const sparkW = () => Math.max(10, inner() - LABEL_W - VALUE_W - 4)
  const g = () => s().snap?.gpu
  const rate = () => s().history.rate.at(-1) ?? 0
  const rows = () => [
    { label: "GPU memory", spark: sparkline(s().history.gpuMem, sparkW(), 100),
      value: g() ? `${fmtGB(g()!.used_mib)} / ${fmtGB(g()!.total_mib)} GB` : "—" },
    { label: "GPU load", spark: sparkline(s().history.gpuUtil, sparkW(), 100), value: g() ? `${g()!.util} %` : "—" },
    { label: "Throughput", spark: sparkline(s().history.rate, sparkW()),
      value: `${rate().toFixed(1)} ${s().history.rateUnit} · last 10 min` },
  ]
  const model = () => {
    const m = s().snap?.model
    return m ? `${m.key} · ${m.container} · up ${fmtDuration(m.up_s)}` : "no model container running"
  }
  const logH = () => Math.max(MIN_LOG_H, s().size.height - CHROME_H - FIXED_H)
  const logLines = () => {
    const end = s().log.length - s().logScroll
    return s().log.slice(Math.max(0, end - logH()), end)
  }
  return (
    <box flexDirection="column" flexGrow={1} paddingTop={PAD_TOP}>
      <Section title="GPU & throughput" width={inner()} theme={t} extra="since the panel was opened" />
      <For each={rows()}>
        {(r) => (
          <text>
            <Span fg={t.muted}>{padEnd(r.label, LABEL_W)}</Span>
            <Span fg={t.accent}>{padEnd(r.spark, sparkW())}</Span>
            {"   " + truncate(r.value, VALUE_W)}
          </text>
        )}
      </For>
      <text>
        <Span fg={t.muted}>{padEnd("Model", LABEL_W)}</Span>
        {truncate(oneLine(model()), inner() - LABEL_W)}
      </text>
      <box height={GAP} />
      <Section title="daemon.log" width={inner()} theme={t}
               extra={s().logScroll ? `scrolled ${s().logScroll} lines up` : "tail"} />
      <For each={logLines()}>{(line) => <text>{truncate(oneLine(line), inner())}</text>}</For>
    </box>
  )
}
