import { MIN_H, MIN_W } from "../layout"

export function MinSize(props: { width: number; height: number }) {
  return (
    <box width="100%" height="100%" justifyContent="center" alignItems="center">
      <text>{`window too small: need ${MIN_W}×${MIN_H}, have ${props.width}×${props.height}`}</text>
    </box>
  )
}
