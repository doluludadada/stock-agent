export type Direction = 'up' | 'down' | 'flat'

export function directionOf(value: number): Direction {
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return 'flat'
}

/** A price against a reference, such as the open against the close before it: equal reads as plain ink, as on a quote board. */
export const PRICE_TONE: Record<Direction, string> = { up: 'text-up', down: 'text-down', flat: 'text-foreground' }
