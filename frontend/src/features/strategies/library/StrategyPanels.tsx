import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { RequireUnlock } from '@/shared/ui/unlock'
import { useStrategySettings } from '../api/queries'
import { requiredBars } from '../model/validate'
import { useStrategyLabels } from '../use-formula-text'
import { RuleSummaryList } from './RuleSummaryList'

const RULES_SHOWN = 3
const OTHERS_SHOWN = 5

/** The owner's strategy in use and the other saved ones, for the market overview. */
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
      <RequireUnlock scope="owner" className="py-3">
        <StrategySummary />
      </RequireUnlock>
    </Panel>
  )
}

function StrategySummary() {
  const { t } = useTranslation('strategies')
  const settings = useStrategySettings()
  const labels = useStrategyLabels()
  if (settings.isPending) return <Skeleton className="h-24 rounded-lg" />
  if (settings.isError) return <ErrorState error={settings.error} title={t('library.loadFailed')} onRetry={() => void settings.refetch()} />
  const active = settings.data.strategies.find((strategy) => strategy.id === settings.data.activeStrategyId)
  const others = settings.data.strategies.filter((strategy) => strategy.id !== active?.id)

  return (
    <div className="grid gap-x-8 gap-y-4 md:grid-cols-[minmax(0,1fr)_17rem]">
      {active ? (
        <div className="min-w-0 space-y-2.5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <Link to={paths.editStrategy(active.id)} className="font-semibold hover:text-primary">
              {labels.name(active)}
            </Link>
            <span className="tabular text-xs text-muted-foreground">{t('panel.meta', { rules: active.rules.length, bars: requiredBars(active) })}</span>
          </div>
          {labels.purpose(active) && <p className="text-sm text-pretty text-muted-foreground">{labels.purpose(active)}</p>}
          <RuleSummaryList strategy={active} limit={RULES_SHOWN} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t('panel.none')}</p>
      )}
      <div className="min-w-0">
        <div className="mb-1 flex items-center justify-between gap-2">
          <h3 className="eyebrow">{t('panel.others')}</h3>
          <Link to={paths.newStrategy} className="text-xs text-primary hover:underline">
            {t('action.createShort')}
          </Link>
        </div>
        {others.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t('panel.noOthers')}</p>
        ) : (
          <ul className="divide-y text-sm">
            {others.slice(0, OTHERS_SHOWN).map((strategy) => (
              <li key={strategy.id}>
                <Link to={paths.editStrategy(strategy.id)} className="flex items-center justify-between gap-3 py-1.5 hover:text-primary">
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
