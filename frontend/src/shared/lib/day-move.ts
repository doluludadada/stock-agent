import type { DailyBar } from '@/shared/api'

export interface DayMove {
  change: number
  ratio: number
}

/** Today's move of the holdings valued at a quote that carries the exchange's change: the sum, over what they were worth at the reference prices. */
export function dayMove(holdings: readonly { quantity: number; quoted: DailyBar | undefined }[]): DayMove | null {
  let change = 0
  let before = 0
  for (const { quantity, quoted } of holdings) {
    if (!quoted || quoted.change === null) continue
    change += quantity * quoted.change
    before += quantity * (quoted.close - quoted.change)
  }
  return before > 0 ? { change, ratio: change / before } : null
}
