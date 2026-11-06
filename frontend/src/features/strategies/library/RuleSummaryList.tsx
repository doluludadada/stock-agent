import { useTranslation } from '@/i18n'
import { describeCondition } from '../model/describe'
import type { Strategy } from '../model/types'
import { useFormulaText, useStrategyLabels } from '../use-formula-text'
import { EffectBadge } from './EffectBadge'

/**
 * The strategy's rules as sentences with their effect, each wrapping in full; `named` adds each rule's name, `limit`
 * keeps the first few, and the page that sets it offers the rest.
 */
export function RuleSummaryList({ strategy, named = false, limit, id }: { strategy: Pick<Strategy, 'rules' | 'indicators'>; named?: boolean; limit?: number; id?: string }) {
  const { t } = useTranslation('builder')
  const text = useFormulaText()
  const labels = useStrategyLabels()
  return (
    <ol id={id} className={named ? 'space-y-3' : 'space-y-2'}>
      {strategy.rules.slice(0, limit).map((rule, index) => (
        <li key={rule.id} className={named ? 'space-y-1.5 border-l-2 border-border pl-3' : 'flex items-start gap-2 text-xs'}>
          {named ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium">{labels.rule(rule.name.trim()) || t('rule.label', { index: index + 1 })}</span>
              <EffectBadge effect={rule.effect} />
            </div>
          ) : (
            <EffectBadge effect={rule.effect} className="mt-px" />
          )}
          <p className={named ? 'text-sm leading-relaxed text-pretty first-letter:uppercase' : 'leading-relaxed text-pretty text-muted-foreground first-letter:uppercase'}>
            {describeCondition(rule.condition, strategy, text)}
          </p>
        </li>
      ))}
    </ol>
  )
}
