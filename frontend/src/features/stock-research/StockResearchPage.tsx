import { ArrowLeft, CircleX, Eye, SearchX } from 'lucide-react'
import { useMemo, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { isApiError, useSession, useStockHistory, type StockHistory } from '@/shared/api'
import { HISTORY_BARS } from '@/shared/lib/chart-range'
import { formatDate, formatNumber } from '@/shared/lib/format'
import { isStockId } from '@/shared/lib/stock-ids'
import { cn } from '@/shared/lib/utils'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { PriceTrend } from '@/shared/ui/price-trend'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import { RequireUnlock } from '@/shared/ui/unlock'
import { useStockTechnical, type StockTechnical } from './api'
import { latestReadings, priceOverlays } from './model'

const OVERLAY_COLORS = ['--chart-ma-fast', '--chart-ma-slow'] as const

type StrategyRef = StockTechnical['strategy']

interface StockResearchPageProps {
  code: string
  actions?: (stock: { code: string; name: string }) => ReactNode
  /** The strategy's name as the owner sees it in the library. */
  strategyName: (strategy: StrategyRef) => string
}

export function StockResearchPage({ code, actions, strategyName }: StockResearchPageProps) {
  const { t } = useTranslation('research')
  const listable = isStockId(code)
  const history = useStockHistory(code, HISTORY_BARS, listable)
  if (!listable || isApiError(history.error, 'notFound')) {
    return (
      <StateBlock
        icon={SearchX}
        title={t('notFound.title', { code })}
        description={t('notFound.description')}
        className="rounded-xl border"
        action={
          <Button asChild variant="outline" size="sm">
            <Link to={paths.overview}>{t('back')}</Link>
          </Button>
        }
      />
    )
  }
  if (history.isPending) return <Skeleton className="h-[28rem] rounded-xl" />
  if (history.isError) return <ErrorState error={history.error} title={t('loadFailed')} onRetry={() => void history.refetch()} className="rounded-xl border" />
  return <Research history={history.data} actions={actions} strategyName={strategyName} />
}

function Research({ history, actions, strategyName }: Omit<StockResearchPageProps, 'code'> & { history: StockHistory }) {
  const { t } = useTranslation('research')
  const { unlocked } = useSession('owner')
  const technical = useStockTechnical(history.stock.stock_id)
  const overlays = useMemo(
    () =>
      priceOverlays(technical.data).map((overlay, index) => ({
        key: overlay.key,
        label: t('chart.sma', { period: overlay.period }),
        colorVar: OVERLAY_COLORS[index] ?? '--chart-ma-slow',
        values: overlay.values,
      })),
    [technical.data, t],
  )
  const name = history.stock.name ?? history.stock.stock_id

  return (
    <div className="space-y-4">
      <Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground">
        <Link to={paths.overview}>
          <ArrowLeft aria-hidden />
          {t('back')}
        </Link>
      </Button>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
          <h1 className="display">{name}</h1>
          <span className="font-mono text-sm text-muted-foreground">{history.stock.stock_id}</span>
          <Badge variant="outline" className="font-normal">
            {t(`market.${history.stock.market}`)}
          </Badge>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions({ code: history.stock.stock_id, name })}</div>}
      </header>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <Panel title={t('chart.title')}>
          <PriceTrend bars={history.bars} name={name} kind="price" overlays={overlays} chartHeight={{ price: 300, volume: 84 }} />
        </Panel>

        <Panel title={t('indicator.title')} aside={technical.data && strategyName(technical.data.strategy)} flush>
          <RequireUnlock scope="owner">
            <IndicatorList technical={technical} />
          </RequireUnlock>
        </Panel>
      </div>

      {unlocked && <EvaluationPanel technical={technical} strategyName={strategyName} />}
    </div>
  )
}

type TechnicalQuery = ReturnType<typeof useStockTechnical>

function IndicatorList({ technical }: { technical: TechnicalQuery }) {
  const { t } = useTranslation('research')
  const locale = useLocale()
  if (technical.isPending) return <Skeleton className="m-4 h-64 rounded-lg" />
  if (technical.isError) return <ErrorState error={technical.error} title={t('technicalFailed')} onRetry={() => void technical.refetch()} />
  return (
    <dl className="divide-y text-sm">
      {latestReadings(technical.data).map((row) => (
        <div key={row.indicatorId} className="flex items-start justify-between gap-3 px-4 py-2">
          <dt className="text-muted-foreground">
            <IndicatorName technical={technical.data} indicatorId={row.indicatorId} />
          </dt>
          <dd className="tabular text-right">
            {row.outputs.length === 0
              ? t('insufficient')
              : row.outputs.map(([output, value]) => (
                  <span key={output} className="block">
                    {row.outputs.length > 1 && <span className="mr-1.5 text-xs text-muted-foreground">{t(`formula:output.${output}`)}</span>}
                    {formatNumber(locale, value, Math.abs(value) >= 1000 ? 0 : 2)}
                  </span>
                ))}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function IndicatorName({ technical, indicatorId }: { technical: StockTechnical; indicatorId: string }) {
  const { t } = useTranslation('formula')
  const parameters = technical.strategy.indicators[indicatorId]
  if (!parameters) return indicatorId
  const values = Object.fromEntries(Object.entries(parameters).filter(([key]) => key !== 'kind').map(([key, value]) => [key, String(value)]))
  return t(`indicator.${parameters.kind}`, values)
}

function EvaluationPanel({ technical, strategyName }: { technical: TechnicalQuery; strategyName: StockResearchPageProps['strategyName'] }) {
  const { t } = useTranslation('research')
  const locale = useLocale()
  if (technical.isPending) return <Skeleton className="h-40 rounded-xl" />
  if (technical.isError) return null
  const { report } = technical.data
  const passed = report !== null && report.hard_failures.length === 0
  const lastBar = technical.data.bar_times.at(-1)
  return (
    <Panel
      title={t('evaluation.title')}
      aside={
        <>
          <span>
            {strategyName(technical.data.strategy)}
            {lastBar && ` · ${t('evaluation.lastBar', { date: formatDate(locale, lastBar) })}`}
          </span>
          {report && (
            <span className="flex items-center gap-1.5 text-foreground">
              <span className="text-muted-foreground">{t('evaluation.score')}</span>
              <span className="tabular text-base font-semibold">{report.score}</span>
              <span className={cn('rounded px-1.5 py-0.5 text-xs font-medium', passed ? 'bg-jade-soft text-jade' : 'bg-muted text-muted-foreground')}>
                {t(passed ? 'evaluation.passed' : 'evaluation.excluded')}
              </span>
            </span>
          )}
        </>
      }
    >
      {report === null ? (
        <p className="text-sm text-muted-foreground">{t('evaluation.none')}</p>
      ) : (
        <div className="grid gap-x-6 gap-y-4 md:grid-cols-3">
          <ReportList icon={CircleX} tone="text-destructive" title={t('evaluation.hard')} items={report.hard_failures} empty={t('evaluation.noneListed')} />
          <ReportList icon={CircleX} tone="text-gold" title={t('evaluation.soft')} items={report.soft_failures} empty={t('evaluation.noneListed')} />
          <ReportList icon={Eye} tone="text-jade" title={t('evaluation.observations')} items={report.observations} empty={t('evaluation.noneListed')} />
        </div>
      )}
    </Panel>
  )
}

function ReportList({ icon: Icon, tone, title, items, empty }: { icon: typeof Eye; tone: string; title: string; items: string[]; empty: string }) {
  return (
    <div className="min-w-0">
      <h3 className={cn('mb-1.5 flex items-center gap-1.5 text-xs font-medium', tone)}>
        <Icon aria-hidden className="size-3.5" />
        {title} <span className="tabular text-muted-foreground">{items.length}</span>
      </h3>
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground">{empty}</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {items.map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
