import type { DailyBar } from '@/shared/api'
import { CHART_RANGES, sessionDate } from '@/shared/lib/chart-range'
import type { StockAnalysis, StockFinancials, StockNews, StockTechnical } from './api'

export type RevenueMonth = StockAnalysis['revenue']['months'][number]
export type QuarterResult = StockAnalysis['earnings']['quarters'][number]
export type Reading = StockAnalysis['readings'][number]
export type NewsItem = StockNews['items'][number]

/**
 * How a reading sounds: a rise or a fall takes its direction's icon, a short history is a caution, a missing figure
 * is plain absence, and a valuation against its median takes no side. The sentence comes from the dictionary by kind.
 */
export const READING_TONE = {
  revenue_accelerating: 'up',
  revenue_growing: 'up',
  eps_up: 'up',
  revenue_slowing: 'down',
  revenue_shrinking: 'down',
  eps_down: 'down',
  revenue_history_short: 'short',
  eps_history_short: 'short',
  valuation_history_short: 'short',
  no_revenue: 'none',
  no_eps: 'none',
  no_valuation: 'none',
  no_pe: 'none',
  pe_above_median: 'plain',
  pe_below_median: 'plain',
  pe_at_median: 'plain',
} as const satisfies Record<Reading['kind'], 'up' | 'down' | 'short' | 'none' | 'plain'>

export type ReadingTone = (typeof READING_TONE)[Reading['kind']]

/** Three years of months show a trend and its seasons; the chart draws the latest of them, oldest first. */
export const CHART_MONTHS = 36

export function chartMonths(months: readonly RevenueMonth[]): RevenueMonth[] {
  return months.slice(-CHART_MONTHS)
}

/** The sources the backend can name, each with how its time reads: a board's post and TWSE's news carry a day only. */
export const NEWS_SOURCES = {
  twse_mops: { dayOnly: false },
  twse_news: { dayOnly: true },
  news_media: { dayOnly: false },
  ptt_stock: { dayOnly: true },
  ptt_gossiping: { dayOnly: true },
  reunion: { dayOnly: false },
} as const satisfies Record<NewsItem['source'], { dayOnly: boolean }>

/**
 * A third party's address is a link only when it is plain http or https: anything else (`javascript:`, `data:`, a
 * relative path) gets no link.
 */
export function outboundUrl(url: string | null): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null
  } catch {
    return null
  }
}

/** An open-data item's text, unless it only repeats the title, as TWSE's own news does. */
export function newsText(item: NewsItem): string | null {
  const text = item.open_text?.trim()
  return text && text !== item.title.trim() ? text : null
}

/** The quarters that hold a figure worth a row, newest first. */
export function shownQuarters(quarters: readonly QuarterResult[]): QuarterResult[] {
  return quarters.filter((quarter) => quarter.eps_year_to_date !== null || quarter.gross_margin !== null || quarter.net_margin !== null).reverse()
}

type TechnicalReport = NonNullable<StockTechnical['report']>

/**
 * Pure shaping of the backend's readings for the chart and panels. Nothing here computes an indicator: every value is
 * one the backend's strategy read.
 */

export interface Overlay {
  key: string
  period: number
  /** The moving average at each session the evaluation read, keyed by the session date. */
  values: Map<string, number | null>
}

/** The strategy's moving averages of closes, the only readings drawn on the price axis; at most two, shortest first. */
export function priceOverlays(technical: StockTechnical | undefined): Overlay[] {
  if (!technical) return []
  return Object.entries(technical.strategy.indicators)
    .flatMap(([indicatorId, parameters]) => (parameters.kind === 'sma' ? [{ indicatorId, period: parameters.period }] : []))
    .sort((a, b) => a.period - b.period)
    .slice(0, 2)
    .map(({ indicatorId, period }) => ({
      key: `ma_${indicatorId}`,
      period,
      values: new Map(technical.bar_times.map((ts, index) => [sessionDate(ts), technical.readings[indicatorId]?.[index]?.value ?? null])),
    }))
}

/** Each indicator of the strategy with its outputs at the latest bar the evaluation read. */
export function latestReadings(technical: StockTechnical): { indicatorId: string; outputs: [string, number][] }[] {
  return Object.keys(technical.strategy.indicators).map((indicatorId) => {
    const series = technical.readings[indicatorId] ?? []
    return { indicatorId, outputs: Object.entries(series.at(-1) ?? {}) as [string, number][] }
  })
}

/** The last session: open, high, low and close against the close before it, the day's swing and the volume. */
export interface DayQuote {
  open: number
  high: number
  low: number
  close: number
  volume: number
  previousClose: number | null
  /** The day's high-to-low swing as a share of the close before it. */
  amplitude: number | null
  /** The session, YYYY-MM-DD in Taipei. */
  date: string
}

export function dayQuote(bars: readonly DailyBar[]): DayQuote | null {
  const last = bars.at(-1)
  if (!last) return null
  const previous = bars.at(-2)
  return {
    open: last.open,
    high: last.high,
    low: last.low,
    close: last.close,
    volume: last.volume,
    previousClose: previous?.close ?? null,
    amplitude: previous ? (last.high - last.low) / previous.close : null,
    date: sessionDate(last.ts),
  }
}

export interface YearRange {
  low: number
  high: number
  close: number
  /** The close against the high and the low, as ratios: -0.1 is 10% under the high. */
  fromHigh: number
  fromLow: number
  sessions: number
}

/** The lowest low and highest high of the last year of sessions, and where the last close sits between them. */
export function yearRange(bars: readonly DailyBar[]): YearRange | null {
  const window = bars.slice(-CHART_RANGES['1Y'])
  const last = window.at(-1)
  if (!last) return null
  const high = Math.max(...window.map((bar) => bar.high))
  const low = Math.min(...window.map((bar) => bar.low))
  return { low, high, close: last.close, fromHigh: (last.close - high) / high, fromLow: (last.close - low) / low, sessions: window.length }
}

/** What one rule of the strategy said about the stock, under the rule's own name. */
export interface Check {
  rule: string
  /** For a rule that adds to the score: whether its pattern showed. */
  detected?: boolean
}

const OBSERVATION = /^(.*): (detected|not detected)$/

/**
 * The report names each rule it failed, and each scoring rule as `<name>: detected` or `<name>: not detected`. The
 * names are the strategy's own, a stable key into the rules the same answer carries. The contract answers the
 * observations as these sentences only (`TechnicalReport.observations: string[]`), so the pattern stays until it
 * answers the rule and whether it showed as fields.
 */
export function reportChecks(report: TechnicalReport): { hard: Check[]; soft: Check[]; observations: Check[] } {
  return {
    hard: report.hard_failures.map((rule) => ({ rule })),
    soft: report.soft_failures.map((rule) => ({ rule })),
    observations: report.observations.map((text) => {
      const match = OBSERVATION.exec(text)
      return match ? { rule: match[1]!, detected: match[2] === 'detected' } : { rule: text }
    }),
  }
}

export type QuarterFinancials = StockFinancials['quarters'][number]

/**
 * The figures of a quarter in the order a statement reads: the income of the year to the quarter's end, then the
 * balance at its end. Amounts are in thousands of TWD, per-share figures in TWD.
 */
export const QUARTER_FIGURES = [
  { key: 'revenue', unit: 'amount' },
  { key: 'gross_profit', unit: 'amount' },
  { key: 'operating_income', unit: 'amount' },
  { key: 'net_income', unit: 'amount' },
  { key: 'eps', unit: 'perShare' },
  { key: 'total_assets', unit: 'amount' },
  { key: 'total_liabilities', unit: 'amount' },
  { key: 'equity', unit: 'amount' },
  { key: 'book_value_per_share', unit: 'perShare' },
] as const satisfies readonly { key: Exclude<keyof QuarterFinancials, 'quarter'>; unit: 'amount' | 'perShare' }[]

export type QuarterFigure = (typeof QUARTER_FIGURES)[number]
