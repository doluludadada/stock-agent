export type Direction = 'up' | 'down' | 'flat'

export function directionOf(value: number): Direction {
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return 'flat'
}

/** Taiwan convention: red rises, green falls. Every use also shows a sign, an arrow or a word, so color is never the only signal. */
export const DIRECTION_TONE: Record<Direction, { text: string; stroke: string; bar: string }> = {
  up: { text: 'text-up', stroke: 'stroke-up', bar: 'bg-up' },
  down: { text: 'text-down', stroke: 'stroke-down', bar: 'bg-down' },
  flat: { text: 'text-flat', stroke: 'stroke-flat', bar: 'bg-flat' },
}

/** A price against a reference, such as the open against the close before it: equal reads as plain ink, as on a quote board. */
export const PRICE_TONE: Record<Direction, string> = { up: DIRECTION_TONE.up.text, down: DIRECTION_TONE.down.text, flat: 'text-foreground' }
