import type { Schemas } from '@/shared/api'
import { HISTORY_BARS, pricePoints, summarize } from './chart-range'

type DailyBar = Schemas['DailyBarResponse']

function bars(closes: number[], extremes: Partial<Record<number, { high?: number; low?: number; open?: number }>> = {}): DailyBar[] {
  const start = Date.UTC(2026, 0, 5, 5, 30)
  return closes.map((close, index) => ({
    ts: new Date(start + index * 86_400_000).toISOString(),
    open: extremes[index]?.open ?? close,
    high: extremes[index]?.high ?? close,
    low: extremes[index]?.low ?? close,
    close,
    volume: 1000 + index,
    change: null,
  }))
}

describe('summarize', () => {
  it('has nothing to say without sessions', () => {
    expect(summarize([], '1M')).toBeNull()
  })

  it("measures the day's change against the session before, says so, and names the session in Taipei", () => {
    const summary = summarize(bars([100, 110]), '1M')!
    expect(summary.close).toBe(110)
    expect(summary.dayChange).toEqual({ value: 10, ratio: 0.1, basis: 'previousClose' })
    expect(summary.volume).toBe(1001)
    expect(summary.date).toBe('2026-01-06')
  })

  it("takes the exchange's change against the reference price, which an ex-dividend day lowers", () => {
    const history = bars([100, 96.5])
    history[1] = { ...history[1]!, change: -0.5 }
    expect(summarize(history, '1M')!.dayChange).toEqual({ value: -0.5, ratio: -0.5 / 97, basis: 'reference' })
  })

  it("measures a range's change from the close before the range starts", () => {
    const closes = Array.from({ length: 30 }, (_, index) => 100 + index)
    const summary = summarize(bars(closes), '1M')!
    expect(summary.rangeChangeRatio).toBeCloseTo((129 - 108) / 108)
  })

  it('asks for enough history that the longest range has a base before it', () => {
    const closes = Array.from({ length: HISTORY_BARS }, (_, index) => (index === 0 ? 50 : 100))
    expect(summarize(bars(closes), '1Y')!.rangeChangeRatio).toBeCloseTo(1)
  })

  it('keeps the high and low of the range, not of older sessions', () => {
    const closes = Array.from({ length: 30 }, () => 100)
    const summary = summarize(bars(closes, { 2: { high: 500, low: 1 }, 25: { high: 120, low: 90 } }), '1M')!
    expect(summary.rangeHigh).toBe(120)
    expect(summary.rangeLow).toBe(90)
  })

  it('reports no day change for a single session', () => {
    const summary = summarize(bars([100]), '3M')!
    expect(summary.dayChange).toBeNull()
    expect(summary.rangeChangeRatio).toBe(0)
  })
})

describe('pricePoints', () => {
  it("keeps the range's sessions and marks each against the close before, including the one before the range", () => {
    const closes = [...Array.from({ length: 20 }, () => 100), 99, ...Array.from({ length: 20 }, (_, index) => 100 + index)]
    const points = pricePoints(bars(closes), '1M')
    expect(points).toHaveLength(21)
    expect(points[0]).toMatchObject({ value: 99, up: false })
    expect(points[1]).toMatchObject({ value: 100, up: true })
  })

  it('compares the first session of the history with its own open', () => {
    expect(pricePoints(bars([100], { 0: { open: 101 } }), '1M')[0]!.up).toBe(false)
  })
})
