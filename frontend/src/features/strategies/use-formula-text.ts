import { useCallback, useMemo } from 'react'
import { useLocale, useTranslation } from '@/i18n'
import { strategyFromApi, type ApiStrategy } from './api/mapping'
import { describeCondition, type FormulaText } from './model/describe'
import { isBuiltInId } from './model/settings'
import type { Strategy } from './model/types'

export function useFormulaText(): FormulaText {
  const { t } = useTranslation()
  const locale = useLocale()
  return useMemo(() => {
    const format = new Intl.NumberFormat(locale, { maximumFractionDigits: 4 })
    return { t: (key, params) => t(key, params), number: (value) => format.format(value) }
  }, [t, locale])
}

/**
 * A strategy's name is the owner's own text. The three built-in ids also get a translated name, while the name is
 * still the built-in's, and a translated purpose: the backend stores no description.
 */
export function useStrategyLabels() {
  const { t } = useTranslation('strategies')
  return useMemo(() => {
    const builtIn = (strategy: { id: string }) => isBuiltInId(strategy.id)
    return {
      name: (strategy: { id: string; name: string }) => {
        if (builtIn(strategy) && strategy.name === t(`builtin.${strategy.id}.apiName`)) return t(`builtin.${strategy.id}.name`)
        return strategy.name.trim() || t('untitled')
      },
      purpose: (strategy: Strategy) => (builtIn(strategy) ? t(`builtin.${strategy.id}.purpose`) : ''),
    }
  }, [t])
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
