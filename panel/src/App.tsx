import { onResize, useKeyboard, useTerminalDimensions } from "@opentui/solid"
import { createSignal, onCleanup, onMount } from "solid-js"
import type { BridgeLike } from "./bridge/client"
import { Shell } from "./components/Shell"
import { runCommand } from "./effects"
import { initialState, update, type Action, type AppState } from "./state/store"
import { makeTheme } from "./theme"

export interface AppProps {
  client: BridgeLike
  onQuit: () => void
  suspend?: (fn: () => void) => void
  pollMs?: number
  slowPollMs?: number
}

export function App(props: AppProps) {
  const dims = useTerminalDimensions()
  const theme = makeTheme()
  const [state, setState] = createSignal<AppState>(initialState(dims().width, dims().height))
  const ctx = { client: props.client, now: () => Date.now(), suspend: props.suspend }

  const dispatch = (a: Action): void => {
    const { state: next, cmds } = update(state(), a)
    setState(next)
    for (const c of cmds) {
      if (c.kind === "quit") { props.onQuit(); continue }
      void runCommand(c, ctx).then((acts) => acts.forEach(dispatch))
    }
  }

  props.client.onStatus((status) => dispatch({ type: "bridge", status }))
  useKeyboard((k) => dispatch({ type: "key", key: { name: k.name, ctrl: k.ctrl, shift: k.shift, meta: k.meta,
                                                     sequence: k.sequence } }))
  onResize((width, height) => dispatch({ type: "resize", width, height }))

  onMount(() => {
    dispatch({ type: "poll" })
    const fast = setInterval(() => dispatch({ type: "poll" }), props.pollMs ?? 1000)
    const slow = setInterval(() => dispatch({ type: "slowTick", now: Date.now() }), props.slowPollMs ?? 2000)
    onCleanup(() => { clearInterval(fast); clearInterval(slow) })
  })

  return <Shell state={state()} theme={theme} />
}
