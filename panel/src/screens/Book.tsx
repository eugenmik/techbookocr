import { SyntaxStyle } from "@opentui/core"
import { For, Show } from "solid-js"
import { bookInfoLine } from "../components/BookCard"
import { Section } from "../components/Section"
import { Span } from "../components/Span"
import { StageTable } from "../components/StageTable"
import { bookSubline } from "../fixes-view"
import { oneLine, strWidth, truncate } from "../format"
import { CHROME_H, GUTTER } from "../layout"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"

export const BOOK_LEFT_W = 46
const BACK = "‹ Queue   "
const SECTION_H = 2           // header + line
const HEADER_ROWS = 2         // name and description row
// Left-column rows outside the issues list: "Stages" + table header + blank + "Issues".
const FIXED_LEFT = SECTION_H + 1 + 1 + SECTION_H
// In a narrow column (80×24) the top padding and the blank row under the header do not fit.
const roomy = (bodyH: number, rows: number) => bodyH >= HEADER_ROWS + 2 + FIXED_LEFT + rows + 4

// <markdown> in 0.5.14 requires syntaxStyle; created lazily (needs the native library).
let mdStyle: SyntaxStyle | null = null
const markdownStyle = (): SyntaxStyle => (mdStyle ??= SyntaxStyle.create())

export function BookScreen(props: { state: AppState; theme: Theme }) {
  const s = () => props.state
  const d = () => (s().book && s().book!.info.name === s().bookName ? s().book : null)
  const rightW = () => s().size.width - 2 - BOOK_LEFT_W - GUTTER
  const bodyH = () => s().size.height - CHROME_H
  const stageRows = () => {
    const st = d()?.stages ?? []
    // stage table rows: one row per stage + an ETA row for the running stage with an estimate
    return st.length + st.filter((r) => r.status === "running" && r.eta_s != null).length
  }
  const loose = () => roomy(bodyH(), stageRows())
  // Free rows for issues; if they do not all fit, one of them is given to the "+N more" row.
  const avail = () => bodyH() - (loose() ? 2 : 0) - HEADER_ROWS - FIXED_LEFT - stageRows()
  const issuesH = () => {
    const n = d()?.issues.length ?? 0
    return n <= avail() ? n : Math.max(0, avail() - 1)
  }
  const more = () => (d()?.issues.length ?? 0) > issuesH() && avail() >= 1
  const t = props.theme
  return (
    <Show when={d()} fallback={<text fg={t.muted}>{s().bookName ? "loading…" : "select a book on the Queue screen"}</text>}>
      <box flexDirection="column" flexGrow={1} paddingTop={loose() ? 1 : 0}>
        <text>
          <Span fg={t.muted}>{BACK}</Span>
          <strong>{truncate(oneLine(d()!.info.name), s().size.width - 2 - strWidth(BACK))}</strong>
        </text>
        <text fg={t.muted}>{bookSubline(" ".repeat(strWidth(BACK)), bookInfoLine(d()!.info),
                            d()!.info.added_at.slice(0, 16).replace("T", " "), d()!.fixes, s().size.width - 2)}</text>
        <Show when={loose()}><box height={1} /></Show>
        <box flexDirection="row" flexGrow={1}>
          <box flexDirection="column" width={BOOK_LEFT_W}>
            <Section title="Stages" width={BOOK_LEFT_W} theme={t} focused={s().bookPane === "stages"} />
            <Show when={d()!.stages.length} fallback={<text fg={t.muted}>not started yet</text>}>
              <StageTable stages={d()!.stages} theme={t} wide={true} />
            </Show>
            <box height={1} />
            <Section title={`Issues  ${d()!.issues.length}`} width={BOOK_LEFT_W} theme={t} />
            <For each={d()!.issues.slice(0, issuesH())}>
              {(line) => <text><Span fg={t.err}>{"✗ "}</Span>{truncate(oneLine(line), BOOK_LEFT_W - 2)}</text>}
            </For>
            <Show when={more()}>
              <text fg={t.muted}>{`+${d()!.issues.length - issuesH()} more in quality.md`}</text>
            </Show>
          </box>
          <box width={GUTTER} />
          <box flexDirection="column" width={rightW()} flexGrow={1}>
            <Section title="quality.md" width={rightW()} theme={t} focused={s().bookPane === "quality"} />
            <Show when={d()!.quality_md}
                  fallback={<text fg={t.muted}>quality.md appears when the book is assembled</text>}>
              <scrollbox focused={s().bookPane === "quality"} flexGrow={1} flexShrink={1} flexBasis={0} minHeight={0}>
                <markdown content={d()!.quality_md!} syntaxStyle={markdownStyle()} />
              </scrollbox>
            </Show>
          </box>
        </box>
      </box>
    </Show>
  )
}
