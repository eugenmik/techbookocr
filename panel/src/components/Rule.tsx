import type { Theme } from "../theme"

export function Rule(props: { width: number; theme: Theme }) {
  return <text fg={props.theme.muted}>{"─".repeat(Math.max(0, props.width))}</text>
}
