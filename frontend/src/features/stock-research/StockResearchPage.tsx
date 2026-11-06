import { ArrowDown, ArrowLeft, CircleMinus, CirclePlus, CircleX, SearchX } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { isApiError, useIsSignedIn, useStockHistory, type StockHistory } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { HISTORY_BARS, summarize } from '@/shared/lib/chart-range'
import { formatNumber, formatSignedPercent, useFormat } from '@/shared/lib/format'
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
import { useStockTechnical, type StockTechnical } from './api'
import { FinancialsPanel } from './FinancialsPanel'
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
  /** A rule's name in the reader's language; the report's name stays the key. */
  ruleName: (name: string) => string
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
        className="rounded-2xl border bg-card py-12"
        action={
          <Button asChild variant="outline">
            <Link to={paths.market}>{t('back')}</Link>
          </Button>
        }
      />
    )
  }
  if (history.isPending) return <Skeleton className="h-[32rem] rounded-2xl" />
  if (history.isError) return <ErrorState error={history.error} title={t('loadFailed')} onRetry={() => void history.refetch()} className="rounded-2xl border bg-card py-12" />
  return <Research history={history.data} actions={actions} strategyName={strategyName} ruleSentences={ruleSentences} ruleName={ruleName} />
}

function Research({ history, actions, strategyName, ruleSentences, ruleName }: Omit<StockResearchPageProps, 'code'> & { history: StockHistory }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const signedIn = useIsSignedIn()
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
  const summary = useMemo(() => summarize(history.bars, '1M'), [history.bars])
  const name = history.stock.name ?? history.stock.stock_id

  return (
    <div className="space-y-5 lg:space-y-6">
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

      <div className="grid items-start gap-4 lg:gap-5 xl:grid-cols-12">
        <Panel className="xl:col-span-8" title={t('chart.title')} description={t('chart.question')}>
          <PriceTrend bars={history.bars} name={name} kind="price" overlays={overlays} quote={false} />
        </Panel>
        <div className="grid content-start items-start gap-4 md:grid-cols-2 lg:gap-5 xl:col-span-4 xl:grid-cols-1">
          <DayPanel history={history} />
          <YearPanel history={history} />
          <div className="md:col-span-2 xl:col-span-1">
            <RequireSignIn reason={t('signIn')} className="rounded-2xl border bg-card">
              <VerdictPanel technical={technical} strategyName={strategyName} />
            </RequireSignIn>
          </div>
        </div>
      </div>

      <FinancialsPanel stockId={history.stock.stock_id} />

      {signedIn && technical.data && <EvaluationDetails technical={technical.data} ruleSentences={ruleSentences} ruleName={ruleName} />}
    </div>
  )
}

/** The last session: open, high and low against the close before it, the swing and the volume in lots. */
function DayPanel({ history }: { history: StockHistory }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const day = dayQuote(history.bars)
  if (!day) return null
  return (
    <Panel title={t('day.title')} description={t('day.question', { date: format.monthDay(day.date) })}>
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
        <Stat label={t('day.previousClose')}>{day.previousClose === null ? '—' : format.price(day.previousClose)}</Stat>
        <Stat label={t('day.amplitude')}>{day.amplitude === null ? '—' : `${format.number(day.amplitude * 100, 2)}%`}</Stat>
        <Stat label={t('day.volume')}>{format.lots(day.volume)}</Stat>
      </dl>
    </Panel>
  )
}

/** Where the close sits inside the last year's range. */
function YearPanel({ history }: { history: StockHistory }) {
  const { t } = useTranslation('research')
  const locale = useLocale()
  const format = useFormat()
  const year = yearRange(history.bars)
  if (!year) return null
  return (
    <Panel title={t('year.title')} description={t('year.question', { count: year.sessions })}>
      <div className="space-y-3">
        <RangeMeter low={year.low} high={year.high} value={year.close} lowLabel={t('year.low')} highLabel={t('year.high')} format={format.price} />
        <p className="flex flex-wrap justify-between gap-x-4 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
          <span>
            {t('year.fromHigh')} <span className="tabular font-medium text-foreground">{formatSignedPercent(locale, year.fromHigh, 1)}</span>
          </span>
          <span>
            {t('year.fromLow')} <span className="tabular font-medium text-foreground">{formatSignedPercent(locale, year.fromLow, 1)}</span>
          </span>
        </p>
      </div>
    </Panel>
  )
}

/** The answer of the user's strategy for this stock: the score, pass or exclusion, and how many checks said what. */
function VerdictPanel({ technical, strategyName }: { technical: TechnicalQuery; strategyName: StockResearchPageProps['strategyName'] }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  if (technical.isPending) return <Skeleton className="h-44 rounded-2xl" />
  if (technical.isError) return <ErrorState error={technical.error} title={t('technicalFailed')} onRetry={() => void technical.refetch()} className="rounded-2xl border bg-card" />
  const { report } = technical.data
  const passed = report !== null && report.hard_failures.length === 0
  const lastBar = technical.data.bar_times.at(-1)
  return (
    <Panel
      title={t('evaluation.title')}
      description={[strategyName(technical.data.strategy), lastBar && t('evaluation.lastBar', { date: format.monthDay(lastBar) })].filter(Boolean).join(' · ')}
      aside={
        report && (
          <a href="#evaluation-details" className="inline-flex min-h-11 items-center gap-1 rounded-md px-1 text-xs hover:text-foreground md:min-h-0">
            {t('evaluation.details')}
            <ArrowDown aria-hidden className="size-3.5" />
          </a>
        )
      }
    >
      {report === null ? (
        <p className="text-sm text-muted-foreground">{t('evaluation.none')}</p>
      ) : (
        <div className="space-y-4">
          <div className="flex items-end justify-between gap-3">
            <p className="flex items-baseline gap-1.5">
              <span className="figure">{report.score}</span>
              <span className="text-xs text-muted-foreground">{t('evaluation.score')}</span>
            </p>
            <span className={cn('rounded-full px-2.5 py-1 text-xs font-medium', passed ? 'bg-brand-soft text-brand' : 'bg-muted text-muted-foreground')}>
              {t(passed ? 'evaluation.passed' : 'evaluation.excluded')}
            </span>
          </div>
          <dl className="grid grid-cols-3 gap-2 text-center">
            <VerdictCount label={t('evaluation.hard')} count={report.hard_failures.length} tone="text-destructive" />
            <VerdictCount label={t('evaluation.soft')} count={report.soft_failures.length} tone="text-gold" />
            <VerdictCount label={t('evaluation.observations')} count={report.observations.length} tone="text-brand" />
          </dl>
        </div>
      )}
    </Panel>
  )
}

function VerdictCount({ label, count, tone }: { label: string; count: number; tone: string }) {
  return (
    <div className="rounded-xl bg-muted/70 px-2 py-2.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('tabular mt-0.5 text-lg font-semibold', count > 0 ? tone : 'text-muted-foreground')}>{count}</dd>
    </div>
  )
}

/** Every check the strategy made, in the reader's words, and each indicator it read at the last bar. */
function EvaluationDetails({ technical, ruleSentences, ruleName }: { technical: StockTechnical } & Pick<StockResearchPageProps, 'ruleSentences' | 'ruleName'>) {
  const { t } = useTranslation('research')
  const sentences = useMemo(() => ruleSentences?.(technical.strategy) ?? new Map<string, string>(), [ruleSentences, technical.strategy])
  if (!technical.report) return null
  const checks = reportChecks(technical.report)
  return (
    <div id="evaluation-details" className="scroll-mt-20 space-y-4 lg:space-y-5">
      <Panel title={t('evaluation.detailsTitle')} description={t('evaluation.detailsQuestion')}>
        <div className="grid gap-x-8 gap-y-6 @2xl:grid-cols-2 @5xl:grid-cols-3">
          <CheckList icon={CircleX} tone="text-destructive" title={t('evaluation.hard')} checks={checks.hard} sentences={sentences} ruleName={ruleName} />
          <CheckList icon={CircleMinus} tone="text-gold" title={t('evaluation.soft')} checks={checks.soft} sentences={sentences} ruleName={ruleName} />
          <CheckList icon={CirclePlus} tone="text-brand" title={t('evaluation.observations')} checks={checks.observations} sentences={sentences} ruleName={ruleName} />
        </div>
      </Panel>
      <IndicatorPanel technical={technical} />
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

function IndicatorPanel({ technical }: { technical: StockTechnical }) {
  const { t } = useTranslation('research')
  const locale = useLocale()
  const format = useFormat()
  /** A volume average reads in lots like every volume; other readings keep two decimals under 1,000. */
  const reading = (strategy: StockTechnical, indicatorId: string, value: number) =>
    strategy.strategy.indicators[indicatorId]?.kind === 'volume_sma' ? format.lots(value) : formatNumber(locale, value, Math.abs(value) >= 1000 ? 0 : 2)
  const [expanded, setExpanded] = useState(false)
  const readings = latestReadings(technical)
  return (
    <Panel
      title={t('indicator.title')}
      description={t('indicator.question')}
      footer={
        readings.length > READINGS_SHOWN && (
          <ShowMore
            expanded={expanded}
            onToggle={() => setExpanded(!expanded)}
            controls="indicator-readings"
            moreLabel={t('indicator.showAll', { count: readings.length })}
            lessLabel={t('indicator.showLess')}
          />
        )
      }
    >
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
                      <span className="font-medium">{reading(technical, row.indicatorId, value)}</span>
                    </span>
                  ))}
            </dd>
          </div>
        ))}
      </dl>
    </Panel>
  )
}

function IndicatorName({ technical, indicatorId }: { technical: StockTechnical; indicatorId: string }) {
  const { t } = useTranslation('formula')
  const parameters = technical.strategy.indicators[indicatorId]
  if (!parameters) return indicatorId
  const values = Object.fromEntries(Object.entries(parameters).filter(([key]) => key !== 'kind').map(([key, value]) => [key, String(value)]))
  return t(`indicator.${parameters.kind}`, values)
}
