import { useMemo } from 'react'
import { builtInRuleName, useLocale, useTranslation } from '@/i18n'

/**
 * The developer's strategies in config/strategies; an owner strategy may keep one of these ids. A saved copy of a
 * built-in that no longer ships (`conservative`, `aggressive`) is one of the owner's own strategies.
 */
export const BUILT_IN_IDS = ['balanced'] as const
export type BuiltInId = (typeof BUILT_IN_IDS)[number]

export function isBuiltInId(id: string): id is BuiltInId {
  return (BUILT_IN_IDS as readonly string[]).includes(id)
}

/**
 * A strategy's name is the owner's own text. A built-in id also gets a translated name, while the name is
 * still the built-in's, and a translated purpose: the backend stores no description. A rule's name is the owner's text
 * too, shown as typed, except a built-in strategy's own rule: in a strategy with a built-in id, a rule that still has
 * a name the built-ins ship reads in the reader's language. The strategy's id decides, never the name alone, so a
 * name the owner typed in their own strategy stays as typed even when a built-in rule has it. The name the backend
 * matches stays as it is.
 */
export function useStrategyLabels() {
  const { t } = useTranslation('strategies')
  const locale = useLocale()
  return useMemo(
    () => ({
      name: (strategy: { id: string; name: string }) => {
        if (isBuiltInId(strategy.id) && strategy.name === t(`builtin.${strategy.id}.apiName`)) return t(`builtin.${strategy.id}.name`)
        return strategy.name.trim() || t('untitled')
      },
      purpose: (strategy: { id: string }) => (isBuiltInId(strategy.id) ? t(`builtin.${strategy.id}.purpose`) : ''),
      rule: (strategyId: string | null | undefined, name: string) => (strategyId && isBuiltInId(strategyId) ? builtInRuleName(locale, name) : name),
    }),
    [t, locale],
  )
}
