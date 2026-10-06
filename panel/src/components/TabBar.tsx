import { Span } from "./Span"
import { For, Show } from "solid-js"
import type { Screen } from "../state/store"
import type { Theme } from "../theme"

const TABS: [Screen, string][] = [["queue", "1 Queue"], ["book", "2 Book"], ["telemetry", "3 Telemetry"], ["settings", "4 Settings"]]

export function TabBar(props: { screen: Screen; theme: Theme }) {
  return (
    <text>
      <span>{"  "}</span>
      <For each={TABS}>
        {([id, label]) => (
          <Show when={props.screen === id}
                fallback={<Span fg={props.theme.muted}>{` ${label} `}{"   "}</Span>}>
            <Span fg={props.theme.accent}><strong>{`[${label}]`}</strong>{"   "}</Span>
          </Show>
        )}
      </For>
    </text>
  )
}
