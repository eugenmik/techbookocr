import { Span } from "./Span"
import type { Theme } from "../theme"
import { Rule } from "./Rule"

/** Block header + thin line: blocks are separated this way, without frames. */
export function Section(props: { title: string; width: number; theme: Theme; focused?: boolean; extra?: string }) {
  return (
    <box flexDirection="column">
      <text>
        {props.focused
          ? <Span fg={props.theme.accent}><strong>{props.title}</strong></Span>
          : <strong>{props.title}</strong>}
        <Span fg={props.theme.muted}>{props.extra ? `  ${props.extra}` : ""}</Span>
      </text>
      <Rule width={props.width} theme={props.theme} />
    </box>
  )
}
