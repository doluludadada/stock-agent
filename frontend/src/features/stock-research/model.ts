import type { DailyBar } from '@/shared/api'
import { CHART_RANGES, sessionDate } from '@/shared/lib/chart-range'
import type { StockTechnical } from './api'

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
 * names are the strategy's own, a stable key into the rules the same answer carries.
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
