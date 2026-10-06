import { join } from "node:path"
import { For, Match, Show, Switch } from "solid-js"
import { Span } from "../components/Span"
import { padEnd, oneLine, truncate } from "../format"
import { CHROME_H } from "../layout"
import { BINDINGS, type Scope } from "../state/keys"
import type { AppState } from "../state/store"
import type { Theme } from "../theme"
import { windowTop } from "./Queue"

export const HELP_SCOPES: [Scope, string][] = [
  ["global", "Everywhere"], ["daemon", "Daemon (Queue, Book, Telemetry)"], ["queue", "Queue"], ["book", "Book"],
  ["telemetry", "Telemetry"], ["settings", "Settings"], ["add", "Add books"],
]

const prettyKey = (k: string) =>
  ({ up: "↑", down: "↓", left: "←", right: "→", enter: "⏎", space: "␣", escape: "esc", backspace: "⌫",
     pageup: "PgUp", pagedown: "PgDn", tab: "Tab", "ctrl+s": "^S", "ctrl+c": "^C" } as Record<string, string>)[k] ?? k

type AddModal = Extract<NonNullable<AppState["modal"]>, { kind: "add" }>
type ConfirmModal = Extract<NonNullable<AppState["modal"]>, { kind: "confirm" }>

/** Modal window is the only place with a frame; frame height is at most the screen body. */
export function ModalView(props: { state: AppState; theme: Theme }) {
  const s = () => props.state
  const t = props.theme
  const w = () => Math.min(90, s().size.width - 4)
  const bodyH = () => s().size.height - CHROME_H
  const listH = () => Math.max(3, bodyH() - 4)           // frame 2 + header + blank line
  let top = 0                                            // Add books list window, as on Queue
  return (
    <box flexDirection="column" flexGrow={1} alignItems="center">
      <Switch>
        <Match when={s().modal?.kind === "help"}>
          <box border borderStyle="rounded" borderColor={t.accent} width={w()} height={bodyH()} flexDirection="column"
               paddingLeft={2} paddingRight={2}>
            <text><strong>Keys</strong><Span fg={t.muted}>{"  ↑↓ scroll"}</Span></text>
            <scrollbox focused flexGrow={1}>
              <For each={HELP_SCOPES}>
                {([scope, title]) => (
                  <box flexDirection="column">
                    <box height={1} />
                    <text fg={t.accent}>{title}</text>
                    <For each={BINDINGS.filter((b) => b.scope === scope)}>
                      {(b) => <text><Span fg={t.accent}>{padEnd(b.keys.map(prettyKey).join(" "), 12)}</Span>{b.label}</text>}
                    </For>
                  </box>
                )}
              </For>
            </scrollbox>
          </box>
        </Match>
        <Match when={s().modal?.kind === "add" && (s().modal as AddModal)}>
          {(m: () => AddModal) => {
            const marked = (name: string) => m().marked.includes(join(m().dir, name))
            const start = () => (top = windowTop(top, m().cursor, listH(), m().entries.length))
            return (
              <box border borderStyle="rounded" borderColor={t.accent} width={w()} height={bodyH()} flexDirection="column"
                   paddingLeft={2} paddingRight={2}>
                <text>
                  <strong>Add books</strong>
                  <Span fg={t.muted}>{"  " + truncate(oneLine(m().dir), w() - 30)}</Span>
                  <Span fg={t.accent}>{m().marked.length ? `  ${m().marked.length} marked` : ""}</Span>
                </text>
                <box height={1} />
                <Show when={m().entries.length} fallback={<text fg={t.muted}>no folders or .djvu/.pdf files here</text>}>
                  <For each={m().entries.slice(start(), start() + listH())}>
                    {(e, i) => (
                      <text>
                        <Span fg={t.accent}>{start() + i() === m().cursor ? "❯ " : "  "}</Span>
                        <Span fg={t.accent}>{marked(e.name) ? "● " : "  "}</Span>
                        <Span fg={e.dir ? t.muted : undefined}>{truncate(oneLine(e.name), w() - 12) + (e.dir ? "/" : "")}</Span>
                      </text>
                    )}
                  </For>
                </Show>
              </box>
            )
          }}
        </Match>
        <Match when={s().modal?.kind === "confirm" && (s().modal as ConfirmModal)}>
          {(m: () => ConfirmModal) => (
            <box border borderStyle="rounded" borderColor={t.accent} width={w()} flexDirection="column"
                 paddingLeft={2} paddingRight={2}>
              <text><strong>{truncate(m().text, w() - 6)}</strong></text>
              <box height={1} />
              <text fg={t.accent}>{"y yes   n no"}</text>
            </box>
          )}
        </Match>
      </Switch>
    </box>
  )
}
