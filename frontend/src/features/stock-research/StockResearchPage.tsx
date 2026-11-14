import { ArrowLeft, CircleMinus, CirclePlus, CircleX, SearchX } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useTranslation } from '@/i18n'
import { usePageTitle } from '@/shared/lib/page-title'
import { isApiError, useStockHistory, type StockHistory } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { HISTORY_BARS, summarize } from '@/shared/lib/chart-range'
import { DASH, useFormat } from '@/shared/lib/format'
import { isStockId } from '@/shared/lib/stock-ids'
import { cn } from '@/shared/lib/utils'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ErrorState } from '@/shared/ui/error-state'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { Panel } from '@/shared/ui/panel'
import { PriceTrend } from '@/shared/ui/price-trend'
import { PriceValue } from '@/shared/ui/price-value'
import { QuoteHeadline } from '@/shared/ui/quote-headline'
import { RangeMeter } from '@/shared/ui/range-meter'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { ShowMore } from '@/shared/ui/show-more'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { AnalysisPanel } from './AnalysisPanel'
import { useStockTechnical, type StockTechnical } from './api'
import { SECTION_ANCHORS } from './brief'
import { BriefPanel } from './BriefPanel'
import { CompanyPanel } from './CompanyPanel'
import { FinancialsPanel } from './FinancialsPanel'
import { NewsPanel } from './NewsPanel'
import { StockSummary } from './StockSummary'
import { dayQuote, latestReadings, priceOverlays, reportChecks, yearRange, type Check } from './model'

const OVERLAY_COLORS = ['--chart-ma-fast', '--chart-ma-slow'] as const

type StrategyRef = StockTechnical['strategy']
type TechnicalQuery = ReturnType<typeof useStockTechnical>

interface StockResearchPageProps {
  code: string
  actions?: (stock: { code: string; name: string }) => ReactNode
  /** The strategy's name as the user sees it in the library. */
  strategyName: (strategy: StrategyRef) => string
  /** Each rule of the strategy as a sentence in the reader's language, keyed by the rule name a report uses. */
  ruleSentences?: (strategy: StrategyRef) => ReadonlyMap<string, string>
  /** A rule's name as the reader sees it, by the strategy that holds it; the report's name stays the key. */
  ruleName: (strategy: StrategyRef, name: string) => string
}

export function StockResearchPage({ code, actions, strategyName, ruleSentences, ruleName }: StockResearchPageProps) {
  const { t } = useTranslation('research')
  const listable = isStockId(code)
  const history = useStockHistory(code, HISTORY_BARS, listable)
  if (!listable || isApiError(history.error, 'notFound')) {
    return (
      <StateBlock
        icon={SearchX}
        title={t('notFound.title', { code })}
        description={t('notFound.description')}
        framed
        action={
          <Button asChild variant="outline">
            <Link to={paths.market}>{t('back')}</Link>
          </Button>
        }
      />
    )
  }
  if (history.isPending) return <Skeleton className="h-[32rem] rounded-2xl" />
  if (history.isError) return <ErrorState error={history.error} title={t('loadFailed')} onRetry={() => void history.refetch()} framed />
  if (history.data.bars.length === 0) return <WithoutBars history={history.data} actions={actions} />
  return <Research history={history.data} actions={actions} strategyName={strategyName} ruleSentences={ruleSentences} ruleName={ruleName} />
}

/** A listed stock whose daily history holds no session yet, as while the history cache fills: one line says so. */
function WithoutBars({ history, actions }: { history: StockHistory; actions: StockResearchPageProps['actions'] }) {
  const { t } = useTranslation('research')
  return (
    <div className="page-stack">
      <StockHeader history={history} actions={actions} />
      <p className="text-sm text-muted-foreground">{t('noBars')}</p>
      <StockSummary stockId={history.stock.stock_id} />
      <CompanyPanel stockId={history.stock.stock_id} />
      <div id={SECTION_ANCHORS.news}>
        <NewsPanel stockId={history.stock.stock_id} />
      </div>
      <StockTables stockId={history.stock.stock_id} />
    </div>
  )
}

function StockHeader({ history, actions }: { history: StockHistory; actions: StockResearchPageProps['actions'] }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const summary = useMemo(() => summarize(history.bars, '1M'), [history.bars])
  const name = history.stock.name ?? history.stock.stock_id
  usePageTitle(history.stock.name ? `${history.stock.name} ${history.stock.stock_id}` : history.stock.stock_id)
  return (
    <header className="space-y-3">
      <Link to={paths.market} className="-ml-1 inline-flex min-h-11 items-center gap-1.5 rounded-md px-1 text-sm text-muted-foreground hover:text-foreground md:min-h-8">
        <ArrowLeft aria-hidden className="size-4" />
        {t('back')}
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <h1 className="display">{name}</h1>
            <span className="font-mono text-sm text-muted-foreground">{history.stock.stock_id}</span>
            <Badge variant="outline" className="font-normal text-muted-foreground">
              {t(`market.${history.stock.market}`)}
            </Badge>
          </div>
          {summary && (
            <QuoteHeadline
              value={format.price(summary.close)}
              change={summary.dayChange?.value ?? null}
              changeRatio={summary.dayChange?.ratio ?? null}
              asOf={format.closeOn(summary.date)}
            />
          )}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions({ code: history.stock.stock_id, name })}</div>}
      </div>
      <NotAdviceNote />
    </header>
  )
}

function Research({ history, actions, strategyName, ruleSentences, ruleName }: Omit<StockResearchPageProps, 'code'> & { history: StockHistory }) {
  const { t } = useTranslation('research')
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
    <div className="page-stack">
      <StockHeader history={history} actions={actions} />

      <StockSummary stockId={history.stock.stock_id} />

      <CompanyPanel stockId={history.stock.stock_id} />

      <div className="card-grid xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-8">
          <BriefPanel stockId={history.stock.stock_id} />
        </div>
        <div id={SECTION_ANCHORS.news} className="min-w-0 xl:col-span-4">
          <NewsPanel stockId={history.stock.stock_id} />
        </div>
      </div>

      <div className="card-grid xl:grid-cols-12">
        <div id={SECTION_ANCHORS.price} className="xl:col-span-8">
          <Panel title={t('chart.title')}>
            <PriceTrend bars={history.bars} name={name} kind="price" overlays={overlays} quote={false} />
          </Panel>
        </div>
        <div className="card-grid content-start md:grid-cols-2 xl:col-span-4 xl:grid-cols-1">
          <DayPanel history={history} />
          <YearPanel history={history} />
        </div>
      </div>

      <StockTables stockId={history.stock.stock_id} />

      <RequireSignIn reason={t('signIn')} className="rounded-2xl border bg-card">
        <Evaluation technical={technical} strategyName={strategyName} ruleSentences={ruleSentences} ruleName={ruleName} />
      </RequireSignIn>
    </div>
  )
}

/** The tables behind the summary: the financial analysis, then the statements it read. Both start closed on a phone. */
function StockTables({ stockId }: { stockId: string }) {
  return (
    <>
      <AnalysisPanel stockId={stockId} />
      <div id={SECTION_ANCHORS.earnings}>
        <FinancialsPanel stockId={stockId} />
      </div>
    </>
  )
}

/** The last session: open, high and low against the close before it, the swing and the volume in lots. */
function DayPanel({ history }: { history: StockHistory }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const day = dayQuote(history.bars)
  if (!day) return null
  return (
    <Panel title={t('day.title')} aside={<span className="tabular">{format.monthDay(day.date)}</span>}>
      <dl className="grid grid-cols-3 gap-x-4 gap-y-3">
        <Stat label={t('day.open')}>
          <PriceValue value={day.open} reference={day.previousClose} />
        </Stat>
        <Stat label={t('day.high')}>
          <PriceValue value={day.high} reference={day.previousClose} />
        </Stat>
        <Stat label={t('day.low')}>
          <PriceValue value={day.low} reference={day.previousClose} />
        </Stat>
        <Stat label={t('day.previousClose')}>{day.previousClose === null ? DASH : format.price(day.previousClose)}</Stat>
        <Stat label={t('day.amplitude')}>{day.amplitude === null ? DASH : format.percent(day.amplitude, 2)}</Stat>
        <Stat label={t('day.volume')}>{format.lots(day.volume)}</Stat>
      </dl>
    </Panel>
  )
}

/** Where the close sits inside the last year's range. */
function YearPanel({ history }: { history: StockHistory }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const year = yearRange(history.bars)
  if (!year) return null
  return (
    <Panel title={t('year.title')}>
      <div className="space-y-3">
        <RangeMeter low={year.low} high={year.high} value={year.close} lowLabel={t('year.low')} highLabel={t('year.high')} format={format.price} />
        <p className="flex flex-wrap justify-between gap-x-4 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
          <span>
            {t('year.fromHigh')} <span className="tabular font-medium text-foreground">{format.signedPercent(year.fromHigh, 1)}</span>
          </span>
          <span>
            {t('year.fromLow')} <span className="tabular font-medium text-foreground">{format.signedPercent(year.fromLow, 1)}</span>
          </span>
        </p>
      </div>
    </Panel>
  )
}

/**
 * The answer of the viewer's technical strategy for this stock, closed until asked for: the score with pass or
 * exclusion, every check in the reader's words, and each indicator it read at the last bar.
 */
function Evaluation({ technical, strategyName, ruleSentences, ruleName }: { technical: TechnicalQuery } & Pick<StockResearchPageProps, 'strategyName' | 'ruleSentences' | 'ruleName'>) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const data = technical.data
  const sentences = useMemo(() => (data && ruleSentences?.(data.strategy)) ?? new Map<string, string>(), [ruleSentences, data])
  const lastBar = data?.bar_times.at(-1)
  return (
    <Panel
      fold="always"
      title={t('evaluation.title')}
      description={data && [strategyName(data.strategy), lastBar && t('evaluation.lastBar', { date: format.monthDay(lastBar) })].filter(Boolean).join(' · ')}
    >
      {technical.isPending ? (
        <Skeleton className="h-44 rounded-lg" />
      ) : technical.isError ? (
        <ErrorState error={technical.error} title={t('technicalFailed')} onRetry={() => void technical.refetch()} />
      ) : technical.data.report === null ? (
        <p className="text-sm text-muted-foreground">{t('evaluation.none')}</p>
      ) : (
        <EvaluationReport technical={technical.data} report={technical.data.report} sentences={sentences} ruleName={(rule) => ruleName(technical.data.strategy, rule)} />
      )}
    </Panel>
  )
}

interface EvaluationReportProps {
  technical: StockTechnical
  report: NonNullable<StockTechnical['report']>
  sentences: ReadonlyMap<string, string>
  ruleName: (name: string) => string
}

function EvaluationReport({ technical, report, sentences, ruleName }: EvaluationReportProps) {
  const { t } = useTranslation('research')
  const passed = report.hard_failures.length === 0
  const checks = reportChecks(report)
  return (
    <div className="space-y-5">
      <p className="flex items-baseline gap-2">
        <span className="figure">{report.score}</span>
        <span className="text-xs text-muted-foreground">{t('evaluation.score')}</span>
        <span className={cn('ml-auto rounded-full px-2.5 py-1 text-xs font-medium', passed ? 'bg-brand-soft text-brand' : 'bg-muted text-muted-foreground')}>
          {t(passed ? 'evaluation.passed' : 'evaluation.excluded')}
        </span>
      </p>
      <div className="grid gap-x-8 gap-y-6 @2xl:grid-cols-2 @5xl:grid-cols-3">
        <CheckList icon={CircleX} tone="text-destructive" title={t('evaluation.hard')} checks={checks.hard} sentences={sentences} ruleName={ruleName} />
        <CheckList icon={CircleMinus} tone="text-gold" title={t('evaluation.soft')} checks={checks.soft} sentences={sentences} ruleName={ruleName} />
        <CheckList icon={CirclePlus} tone="text-brand" title={t('evaluation.observations')} checks={checks.observations} sentences={sentences} ruleName={ruleName} />
      </div>
      <IndicatorReadings technical={technical} />
    </div>
  )
}

/**
 * One kind of check: each rule as the sentence the designer writes for it, wrapping in full, with the rule's own name
 * on hover. A rule the strategy no longer holds keeps its name.
 */
function CheckList({
  icon: Icon,
  tone,
  title,
  checks,
  sentences,
  ruleName,
}: {
  icon: typeof CircleX
  tone: string
  title: string
  checks: Check[]
  sentences: ReadonlyMap<string, string>
  ruleName: (name: string) => string
}) {
  const { t } = useTranslation('research')
  return (
    <section className="min-w-0">
      <h3 className={cn('mb-2.5 flex items-center gap-1.5 text-sm font-medium', tone)}>
        <Icon aria-hidden className="size-4" />
        {title} <span className="tabular text-muted-foreground">{checks.length}</span>
      </h3>
      {checks.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('evaluation.noneListed')}</p>
      ) : (
        <ul className="space-y-2.5 text-sm">
          {checks.map((check, index) => (
            <li key={`${check.rule}-${index}`} className="flex items-start justify-between gap-3 border-l-2 pl-3 leading-relaxed" title={ruleName(check.rule)}>
              <span className="min-w-0 text-pretty first-letter:uppercase">{sentences.get(check.rule) ?? ruleName(check.rule)}</span>
              {check.detected !== undefined && (
                <span className={cn('mt-0.5 shrink-0 rounded-full px-2 text-xs leading-5', check.detected ? 'bg-brand-soft text-brand' : 'bg-muted text-muted-foreground')}>
                  {t(check.detected ? 'evaluation.detected' : 'evaluation.notDetected')}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** The first readings are enough to scan; the rest open on request. */
const READINGS_SHOWN = 8

function IndicatorReadings({ technical }: { technical: StockTechnical }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  /** A volume average reads in lots like every volume; other readings keep two decimals under 1,000. */
  const reading = (indicatorId: string, value: number) =>
    technical.strategy.indicators[indicatorId]?.kind === 'volume_sma' ? format.lots(value) : format.number(value, Math.abs(value) >= 1000 ? 0 : 2)
  const [expanded, setExpanded] = useState(false)
  const readings = latestReadings(technical)
  return (
    <section aria-label={t('indicator.title')} className="space-y-2.5 border-t pt-4">
      <h3 className="text-sm font-medium">{t('indicator.title')}</h3>
      <dl id="indicator-readings" className="grid grid-cols-2 gap-2.5 @2xl:grid-cols-3 @4xl:grid-cols-4">
        {(expanded ? readings : readings.slice(0, READINGS_SHOWN)).map((row) => (
          <div key={row.indicatorId} className="min-w-0 rounded-xl bg-muted/70 px-3 py-2.5">
            <dt className="text-xs text-pretty text-muted-foreground">
              <IndicatorName technical={technical} indicatorId={row.indicatorId} />
            </dt>
            <dd className="tabular mt-1 space-y-0.5 text-sm">
              {row.outputs.length === 0
                ? t('insufficient')
                : row.outputs.map(([output, value]) => (
                    <span key={output} className="flex items-baseline justify-between gap-2">
                      {row.outputs.length > 1 && <span className="truncate text-xs text-muted-foreground">{t(`formula:output.${output}`)}</span>}
                      <span className="font-medium">{reading(row.indicatorId, value)}</span>
                    </span>
                  ))}
            </dd>
          </div>
        ))}
      </dl>
      {readings.length > READINGS_SHOWN && (
        <ShowMore expanded={expanded} onToggle={() => setExpanded(!expanded)} controls="indicator-readings" moreLabel={t('indicator.showAll', { count: readings.length })} lessLabel={t('indicator.showLess')} />
      )}
    </section>
  )
}

function IndicatorName({ technical, indicatorId }: { technical: StockTechnical; indicatorId: string }) {
  const { t } = useTranslation('formula')
  const parameters = technical.strategy.indicators[indicatorId]
  if (!parameters) return indicatorId
  const values = Object.fromEntries(Object.entries(parameters).filter(([key]) => key !== 'kind').map(([key, value]) => [key, String(value)]))
  return t(`indicator.${parameters.kind}`, values)
}
