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

/** Each part's share of the session's stocks, in percent, so the three add up to 100. */
export function breadthShares({ advancers, decliners, unchanged }: Breadth): { up: number; flat: number; down: number } {
  const total = advancers + decliners + unchanged
  if (total === 0) return { up: 0, flat: 0, down: 0 }
  return { up: (advancers / total) * 100, flat: (unchanged / total) * 100, down: (decliners / total) * 100 }
}
