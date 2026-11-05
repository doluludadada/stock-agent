import type { DailyBar } from '@/shared/api'
import { dayQuote, reportChecks, yearRange } from './model'

const bar = (ts: string, close: number, high = close, low = close, open = close): DailyBar => ({ ts, open, high, low, close, volume: 1_000_000, change: null })

describe('the last session of a stock', () => {
  it('sets the open, high and low against the close before it, with the swing as a share of that close', () => {
    const quote = dayQuote([bar('2026-11-02T13:30:00+08:00', 100), bar('2026-11-03T13:30:00+08:00', 98, 104, 96, 101)])
    expect(quote).toMatchObject({ open: 101, high: 104, low: 96, close: 98, previousClose: 100, date: '2026-11-03' })
    expect(quote?.amplitude).toBeCloseTo(0.08)
  })

  it('places the close inside the year of sessions', () => {
    const year = yearRange([bar('2026-01-05T13:30:00+08:00', 50, 60, 40), bar('2026-11-03T13:30:00+08:00', 90, 100, 80)])
    expect(year).toMatchObject({ low: 40, high: 100, close: 90, sessions: 2 })
    expect(year?.fromHigh).toBeCloseTo(-0.1)
    expect(year?.fromLow).toBeCloseTo(1.25)
  })
})

describe('the checks of a report', () => {
  it('read the rule names, and whether each scoring pattern showed, so the page can say them in its own words', () => {
    const checks = reportChecks({
      score: 40,
      hard_failures: ['Price Above MA_20'],
      soft_failures: ['ADX Trend 20-50: with Bullish Direction'],
      observations: ['RSI Range 50-70: not detected', 'Golden Cross: detected'],
    })
    expect(checks.hard).toEqual([{ rule: 'Price Above MA_20' }])
    expect(checks.soft).toEqual([{ rule: 'ADX Trend 20-50: with Bullish Direction' }])
    expect(checks.observations).toEqual([
      { rule: 'RSI Range 50-70', detected: false },
      { rule: 'Golden Cross', detected: true },
    ])
  })
})
