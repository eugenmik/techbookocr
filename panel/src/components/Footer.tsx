import { Show } from "solid-js"
import { Span } from "./Span"
import { footerHints } from "../state/keys"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"
import { oneLine, strWidth, truncate } from "../format"

export function Footer(props: { state: AppState; theme: Theme; width: number }) {
  const h = () => footerHints(props.state)
  const right = () => h().right.join("  ")
  const left = () => truncate(h().left.join("  "), Math.max(10, props.width - strWidth(right()) - 4))
  const gap = () => Math.max(2, props.width - strWidth(left()) - strWidth(right()))
  const toast = () => props.state.toast
  return (
    <text>
      <Show when={toast()} fallback={null}>
        <Span fg={toast()!.level === "error" ? props.theme.err : props.theme.ok}>
          {truncate((toast()!.level === "error" ? "✗ " : "✓ ") + oneLine(toast()!.text), props.width)}
        </Span>
      </Show>
      <Show when={!toast()}>
      <Span fg={props.theme.accent}>{left()}</Span>
      <span>{" ".repeat(gap())}</span>
      <Span fg={props.theme.accent}>{right()}</Span>
      </Show>
    </text>
  )
}
