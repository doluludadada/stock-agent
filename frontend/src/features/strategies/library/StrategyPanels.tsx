import { ArrowRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { ShowMore } from '@/shared/ui/show-more'
import { Skeleton } from '@/shared/ui/skeleton'
import { useStrategySettings } from '../api/queries'
import { requiredBars } from '../model/validate'
import { useStrategyLabels } from '../use-formula-text'
import { RuleSummaryList } from './RuleSummaryList'

const RULES_SHOWN = 3
const OTHERS_SHOWN = 5

/** The user's strategy in use and the other saved ones, for the market overview; it lays out by its own width. */
export function StrategySummaryPanel() {
  const { t } = useTranslation('strategies')
  return (
    <Panel
      title={t('panel.title')}
      aside={
        <Button asChild variant="ghost" size="sm" className="-my-1">
          <Link to={paths.strategies}>
            {t('panel.openLibrary')}
            <ArrowRight aria-hidden />
          </Link>
        </Button>
      }
    >
      <RequireSignIn className="py-3" reason={t('summarySignIn')}>
        <StrategySummary />
      </RequireSignIn>
    </Panel>
  )
}

function StrategySummary() {
  const { t } = useTranslation('strategies')
  const settings = useStrategySettings()
  const labels = useStrategyLabels()
  const [allRules, setAllRules] = useState(false)
  if (settings.isPending) return <Skeleton className="h-24 rounded-lg" />
  if (settings.isError) return <ErrorState error={settings.error} title={t('library.loadFailed')} onRetry={() => void settings.refetch()} />
  const active = settings.data.strategies.find((strategy) => strategy.id === settings.data.activeStrategyId)
  const others = settings.data.strategies.filter((strategy) => strategy.id !== active?.id)

  return (
    <div className="grid gap-x-8 gap-y-5 @2xl:grid-cols-[minmax(0,1fr)_17rem]">
      {active ? (
        <div className="min-w-0 space-y-2.5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <Link to={paths.editStrategy(active.id)} className="inline-flex min-h-11 items-center font-semibold hover:text-brand md:min-h-0">
              {labels.name(active)}
            </Link>
            <span className="tabular text-xs text-muted-foreground">{t('panel.meta', { rules: active.rules.length, bars: requiredBars(active) })}</span>
          </div>
          {labels.purpose(active) && <p className="text-sm text-pretty text-muted-foreground">{labels.purpose(active)}</p>}
          <RuleSummaryList id="active-strategy-rules" strategy={active} limit={allRules ? undefined : RULES_SHOWN} />
          {active.rules.length > RULES_SHOWN && (
            <ShowMore
              expanded={allRules}
              onToggle={() => setAllRules(!allRules)}
              controls="active-strategy-rules"
              moreLabel={t('panel.showAllRules', { count: active.rules.length })}
              lessLabel={t('panel.showFewerRules')}
            />
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t('panel.none')}</p>
      )}
      <div className="min-w-0">
        <div className="mb-1 flex items-center justify-between gap-2">
          <h3 className="eyebrow">{t('panel.others')}</h3>
          <Link to={paths.newStrategy} className="inline-flex min-h-11 items-center text-xs text-brand hover:underline md:min-h-0">
            {t('action.createShort')}
          </Link>
        </div>
        {others.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t('panel.noOthers')}</p>
        ) : (
          <ul className="divide-y text-sm">
            {others.slice(0, OTHERS_SHOWN).map((strategy) => (
              <li key={strategy.id}>
                <Link to={paths.editStrategy(strategy.id)} className="flex min-h-11 items-center justify-between gap-3 py-1.5 hover:text-brand md:min-h-9">
                  <span className="truncate">{labels.name(strategy)}</span>
                  <span className="tabular shrink-0 text-xs text-muted-foreground">{t('panel.ruleCount', { count: strategy.rules.length })}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
