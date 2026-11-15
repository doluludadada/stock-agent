import type { Schemas } from '@/shared/api'

type RankingFormula = Schemas['RankingFormula']

/** The formula the site ships as the active one: revenue acceleration and nearness to the 250-session high. */
export const SHIPPED_FORMULA: RankingFormula = {
  name: 'revenue_and_high',
  factors: [
    { kind: 'revenue_acceleration', short_months: 3, long_months: 12 },
    { kind: 'nearness_to_high', high_sessions: 250 },
  ],
  top: 20,
  min_close: 10,
  min_traded_value: 30_000_000,
  traded_value_sessions: 20,
  cash_under_average_sessions: null,
}

/** The shipped formula's two factors with cash while the benchmark is under its 60-session average. */
export const CASH_FORMULA: RankingFormula = { ...SHIPPED_FORMULA, name: 'revenue_and_high_cash_60', cash_under_average_sessions: 60 }
