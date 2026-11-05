import type { MarketBreadth, MarketIndex, Schemas } from '@/shared/api'

export type Breadth = Schemas['Breadth']

/** What the trend chart shows: the TAIEX, or the listed stock or ETF that `?target=` names. */
export type TrendTarget = { kind: 'index'; index: MarketIndex } | { kind: 'stock'; id: string }

/** The trend when no research target is chosen: the TAIEX, from the backend's index history. */
export const DEFAULT_INDEX: MarketIndex = 'taiex'

export interface IndustryBreadth extends Breadth {
  industry: string
}

/** The session's industries, strongest average change first; equal ones in name order. */
export function rankIndustries(industries: MarketBreadth['industries']): IndustryBreadth[] {
  return Object.entries(industries)
    .map(([industry, breadth]) => ({ industry, ...breadth }))
    .sort((a, b) => b.average_change_percent - a.average_change_percent || a.industry.localeCompare(b.industry))
}

export type BreadthMood = 'broadUp' | 'leaningUp' | 'mixed' | 'leaningDown' | 'broadDown'

/** The session in one phrase, from the share of rising stocks among those that moved. */
export function breadthMood({ advancers, decliners }: Breadth): BreadthMood {
  const moved = advancers + decliners
  const up = moved === 0 ? 0.5 : advancers / moved
  if (up >= 0.75) return 'broadUp'
  if (up >= 0.55) return 'leaningUp'
  if (up > 0.45) return 'mixed'
  if (up > 0.25) return 'leaningDown'
  return 'broadDown'
}

/**
 * The name of each end of the ranking, by the sign of what it holds: on a day when every industry fell, the top is
 * the smallest declines, never "the leaders".
 */
export type TopLabel = 'gainers' | 'leastDown' | 'strongest'
export type BottomLabel = 'losers' | 'leastUp' | 'weakest'

export interface IndustryEnds {
  top: { label: TopLabel; rows: IndustryBreadth[] }
  bottom: { label: BottomLabel; rows: IndustryBreadth[] }
}

export function industryEnds(ranked: readonly IndustryBreadth[], count: number): IndustryEnds {
  const top = ranked.slice(0, count)
  const bottom = ranked.slice(-count)
  const change = (row: IndustryBreadth) => row.average_change_percent
  return {
    top: { label: top.every((row) => change(row) > 0) ? 'gainers' : top.every((row) => change(row) <= 0) ? 'leastDown' : 'strongest', rows: top },
    bottom: { label: bottom.every((row) => change(row) < 0) ? 'losers' : bottom.every((row) => change(row) >= 0) ? 'leastUp' : 'weakest', rows: bottom },
  }
}

/** The heat map's steps of an industry's average move, in percent; beyond the last is the strongest tint. */
export const HEAT_STEPS = [0.5, 1.5, 3, 5] as const
export type HeatLevel = 0 | 1 | 2 | 3 | 4

/** How strongly an industry moved, whichever way: 0 is under half a percent, 4 is five percent or more. */
export function heatLevel(averageChangePercent: number): HeatLevel {
  const size = Math.abs(averageChangePercent)
  return HEAT_STEPS.filter((step) => size >= step).length as HeatLevel
}

/**
 * A listed stock's change in its latest session: the exchange's own change against its reference price, which an
 * ex-dividend day lowers below the previous close. Null when the listing gave none.
 */
export function listedChange(today: Schemas['DailyBarResponse'] | null | undefined): { value: number; ratio: number } | null {
  if (!today || today.change === null) return null
  const reference = today.close - today.change
  return { value: today.change, ratio: reference === 0 ? 0 : today.change / reference }
}
