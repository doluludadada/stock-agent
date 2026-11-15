import { useTranslation } from '@/i18n'
import type { Schemas } from '@/shared/api'
import { useFormat } from './format'

/** One way to make the monthly ranking, as the server's settings define it. */
export type RankingFormula = Schemas['RankingFormula']
export type RankingFactor = RankingFormula['factors'][number]

/** A factor's windows under the names its wording uses, whatever its kind. */
function windowsOf(factor: RankingFactor): Record<string, number> {
  switch (factor.kind) {
    case 'revenue_acceleration':
      return { short: factor.short_months, long: factor.long_months }
    case 'revenue_yoy':
      return { months: factor.months }
    case 'nearness_to_high':
      return { sessions: factor.high_sessions }
    case 'price_momentum':
      return { sessions: factor.sessions, skip: factor.skip_sessions }
  }
}

/**
 * How a formula and its factors read, from the definition alone: a formula the settings add later needs no wording of
 * its own. A nearness of 1 is a stock at its high; every other value reads in its factor's unit.
 */
export function useFormulaWords() {
  const { t } = useTranslation()
  const format = useFormat()
  const value = (factor: RankingFactor, measured: number): string => {
    switch (factor.kind) {
      case 'revenue_acceleration':
        return t('formula.times', { value: format.number(measured, 2) })
      case 'nearness_to_high':
        return measured >= 1 ? t('formula.atHigh') : format.signedPercent(measured - 1, 1)
      case 'revenue_yoy':
      case 'price_momentum':
        return format.signedPercent(measured, 1)
    }
  }
  const label = (factor: RankingFactor) => t(`formula.factor.${factor.kind}`, windowsOf(factor))
  return {
    /** A factor with its windows, as a column header or a bar's name. */
    label,
    /** A factor's short name, for a line that lists several. */
    short: (factor: RankingFactor) => t(`formula.short.${factor.kind}`),
    value,
    /** A factor's value as a phrase that stands without a header. */
    phrase: (factor: RankingFactor, measured: number) =>
      factor.kind === 'nearness_to_high' && measured >= 1 ? t('formula.atHigh') : t(`formula.phrase.${factor.kind}`, { value: value(factor, measured) }),
    /** What the formula ranks by. */
    factors: (formula: RankingFormula) => formula.factors.map(label).join(' + '),
    /** When the formula holds cash; null for one that never does. */
    cash: (formula: RankingFormula) => (formula.cash_under_average_sessions == null ? null : t('formula.cash', { sessions: formula.cash_under_average_sessions })),
  }
}
