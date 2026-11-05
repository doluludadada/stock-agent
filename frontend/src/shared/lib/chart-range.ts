import type { DailyBar } from '@/shared/api'
import { MARKET_TIME_ZONE } from './format'

/** The chart ranges, in trading sessions; the overview and the stock page share them. */
export const CHART_RANGES = { '1M': 21, '3M': 63, '6M': 126, '1Y': 250 } as const
export type ChartRange = keyof typeof CHART_RANGES
export const CHART_RANGE_KEYS = Object.keys(CHART_RANGES) as ChartRange[]
export const DEFAULT_RANGE: ChartRange = '3M'

/** Sessions to ask for: the longest range plus the session before it, which is that range's base. */
export const HISTORY_BARS = CHART_RANGES['1Y'] + 1

const SESSION_DATE = new Intl.DateTimeFormat('en-CA', { timeZone: MARKET_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit' })

/** A bar's session as YYYY-MM-DD in Taipei; bars are stamped at the 13:30 close. */
export function sessionDate(ts: string): string {
  return SESSION_DATE.format(new Date(ts))
}

/** One session on the price and volume chart; a moving average drawn over the price adds its value under its key. */
export type PricePoint = {
  date: string
  value: number
  volume: number
  /** Closed at or above the session before; the first bar compares with its own open. */
  up: boolean
  [overlay: string]: number | string | boolean | null
}

export function pricePoints(bars: readonly DailyBar[], range: ChartRange): PricePoint[] {
  const start = Math.max(0, bars.length - CHART_RANGES[range])
  return bars.slice(start).map((bar, index) => {
    const previous = bars[start + index - 1]
    return { date: sessionDate(bar.ts), value: bar.close, volume: bar.volume, up: bar.close >= (previous?.close ?? bar.open) }
  })
}

/**
 * The latest session's change. Taiwan quotes it against the exchange's reference price, which an ex-dividend or
 * ex-rights day lowers below the previous close; the listing reports that change for its latest session. Any other
 * session's change is against the previous close, and `basis` says which one it is.
 */
export interface DayChange {
  value: number
  ratio: number
  basis: 'reference' | 'previousClose'
}

export interface RangeSummary {
  close: number
  /** Null when the history has one session and the exchange reported no change for it. */
  dayChange: DayChange | null
  /** From the close before the range to the last close. */
  rangeChangeRatio: number
  rangeHigh: number
  rangeLow: number
  volume: number
  /** The last session, YYYY-MM-DD in Taipei. */
  date: string
}

function dayChange(last: DailyBar, previous: DailyBar | undefined): DayChange | null {
  if (last.change !== null) return { value: last.change, ratio: last.change / (last.close - last.change), basis: 'reference' }
  if (!previous) return null
  return { value: last.close - previous.close, ratio: (last.close - previous.close) / previous.close, basis: 'previousClose' }
}

export function summarize(bars: readonly DailyBar[], range: ChartRange): RangeSummary | null {
  const window = bars.slice(-CHART_RANGES[range])
  const last = window.at(-1)
  const first = window[0]
  if (!last || !first) return null
  const base = bars.at(-(window.length + 1)) ?? first
  return {
    close: last.close,
    dayChange: dayChange(last, bars.at(-2)),
    rangeChangeRatio: (last.close - base.close) / base.close,
    rangeHigh: Math.max(...window.map((bar) => bar.high)),
    rangeLow: Math.min(...window.map((bar) => bar.low)),
    volume: last.volume,
    date: sessionDate(last.ts),
  }
}
