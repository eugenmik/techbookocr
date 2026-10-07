import { Match, Show, Switch } from "solid-js"
import { BookScreen } from "../screens/Book"
import { FixesScreen } from "../screens/Fixes"
import { ModalView } from "../screens/Modals"
import { QueueScreen } from "../screens/Queue"
import { SettingsScreen } from "../screens/Settings"
import { TelemetryScreen } from "../screens/Telemetry"
import { MIN_H, MIN_W } from "../layout"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"
import { Footer } from "./Footer"
import { MinSize } from "./MinSize"
import { Rule } from "./Rule"
import { StatusStrip } from "./StatusStrip"
import { TabBar } from "./TabBar"

export function Shell(props: { state: AppState; theme: Theme }) {
  const s = () => props.state
  const inner = () => s().size.width - 2
  const banner = () => {
    const b = s().bridge
    if (b.kind === "reconnecting") return `reconnecting… (attempt ${b.attempt}) — ${b.error}${s().snap ? " · data is stale" : ""}`
    if (s().stale && s().snap) return "data is stale"
    return ""
  }
  return (
    <Show when={s().size.width >= MIN_W && s().size.height >= MIN_H}
          fallback={<MinSize width={s().size.width} height={s().size.height} />}>
      <box flexDirection="column" width="100%" height="100%" paddingLeft={1} paddingRight={1}>
        <StatusStrip state={s()} theme={props.theme} width={inner()} />
        <text fg={props.theme.warn}>{banner()}</text>
        <TabBar screen={s().screen} theme={props.theme} />
        <Rule width={inner()} theme={props.theme} />
        <box flexDirection="column" flexGrow={1}>
          <Show when={s().snap || s().modal} fallback={<text fg={props.theme.muted}>connecting to techbookocr…</text>}>
            <Switch>
              <Match when={s().modal}><ModalView state={s()} theme={props.theme} /></Match>
              <Match when={s().screen === "queue"}><QueueScreen state={s()} theme={props.theme} /></Match>
              <Match when={s().screen === "book"}><BookScreen state={s()} theme={props.theme} /></Match>
              <Match when={s().screen === "fixes" && s().fixes}><FixesScreen state={s()} theme={props.theme} /></Match>
              <Match when={s().screen === "telemetry"}><TelemetryScreen state={s()} theme={props.theme} /></Match>
              <Match when={s().screen === "settings"}><SettingsScreen state={s()} theme={props.theme} /></Match>
            </Switch>
          </Show>
        </box>
        <Rule width={inner()} theme={props.theme} />
        <Footer state={s()} theme={props.theme} width={inner()} />
      </box>
    </Show>
  )
}
