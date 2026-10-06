import type { JSX } from "solid-js"

/**
 * Colored fragment inside <text>. In 0.5.14 the `fg` prop on <span> is silently ignored
 * (and absent from the types): color works only via `style`. Selection uses an explicit `bg`:
 * reverse video on a transparent background makes the text invisible.
 */
export function Span(props: { fg?: string; bg?: string; children?: JSX.Element }) {
  const style = () => ({ fg: props.fg, bg: props.bg }) as any
  return <span style={style()}>{props.children}</span>
}
