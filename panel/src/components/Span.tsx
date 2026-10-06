import type { JSX } from "solid-js"

/**
 * Colored fragment inside <text>. In 0.5.14 the `fg` prop on <span> is silently ignored
 * (and absent from the types): color works only via `style`. `inverse` is reverse video (selected row),
 * the style key is `reverse`, not `attributes`.
 */
export function Span(props: { fg?: string; inverse?: boolean; children?: JSX.Element }) {
  const style = () => ({ fg: props.fg, reverse: props.inverse || undefined }) as any
  return <span style={style()}>{props.children}</span>
}
