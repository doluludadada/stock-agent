import { useCallback, useMemo } from 'react'
import { useLocale, useTranslation } from '@/i18n'
import { strategyFromApi, type ApiStrategy } from './api/mapping'
import { describeCondition, type FormulaText } from './model/describe'

export function useFormulaText(): FormulaText {
  const { t } = useTranslation()
  const locale = useLocale()
  return useMemo(() => {
    const format = new Intl.NumberFormat(locale, { maximumFractionDigits: 4 })
    return { t: (key, params) => t(key, params), number: (value) => format.format(value) }
  }, [t, locale])
}

/**
 * Each rule of a strategy the backend evaluated, as the sentence the designer shows, keyed by the rule's name: a
 * report names its rules, and the sentence says the check in the reader's language.
 */
export function useRuleSentences(): (strategy: ApiStrategy) => ReadonlyMap<string, string> {
  const text = useFormulaText()
  return useCallback(
    (strategy: ApiStrategy) => {
      const model = strategyFromApi(strategy)
      return new Map(model.rules.map((rule) => [rule.name, describeCondition(rule.condition, model, text)]))
    },
    [text],
  )
}
