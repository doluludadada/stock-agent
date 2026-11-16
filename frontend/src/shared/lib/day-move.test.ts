import type { DailyBar } from '@/shared/api'
import { dayMove } from './day-move'

const quoted = (ts: string, close: number, change: number | null = 2): DailyBar => ({ ts, open: close, high: close, low: close, close, volume: 1_000, change })

describe('today’s move of the holdings', () => {
  it('sums each quote’s change over what the holdings were worth at the reference prices, and leaves out a holding without one', () => {
    const move = dayMove([
      { quantity: 1_000, quoted: quoted('2026-11-16T10:00:00+08:00', 102, 2) },
      { quantity: 2_000, quoted: quoted('2026-11-16T10:00:00+08:00', 49, -1) },
      { quantity: 500, quoted: undefined },
      { quantity: 500, quoted: quoted('2026-11-16T10:00:00+08:00', 20, null) },
    ])
    expect(move).toEqual({ change: 0, ratio: 0 })
    expect(dayMove([{ quantity: 1_000, quoted: quoted('2026-11-16T10:00:00+08:00', 102, 2) }])).toEqual({ change: 2_000, ratio: 0.02 })
    expect(dayMove([{ quantity: 500, quoted: undefined }])).toBeNull()
  })
})
