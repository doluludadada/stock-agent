import { sessionDate } from '@/shared/lib/chart-range'
import type { StockTechnical } from './api'

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
