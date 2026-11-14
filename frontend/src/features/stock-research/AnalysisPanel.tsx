import { CircleDashed, Hourglass, Scale, TrendingDown, TrendingUp, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { useStockAnalysis, type StockAnalysis } from './api'
import { READING_TONE, shownQuarters, type QuarterResult, type ReadingTone, type RevenueMonth } from './model'

/** A dash wherever a figure is not held or cannot be computed from what is held. */
const DASH = '—'

/** A year of months and two years of quarters are enough to see a trend; older ones stay in the financials below. */
const MONTHS_SHOWN = 12
const QUARTERS_SHOWN = 8

const READING_ICON: Record<ReadingTone, { icon: LucideIcon; tone: string }> = {
  up: { icon: TrendingUp, tone: 'text-up' },
  down: { icon: TrendingDown, tone: 'text-down' },
  short: { icon: Hourglass, tone: 'text-gold' },
  none: { icon: CircleDashed, tone: 'text-muted-foreground' },
  plain: { icon: Scale, tone: 'text-brand' },
}

type Valuation = StockAnalysis['valuation']
type RatioStanding = Valuation['pe_ratio']

/**
 * The stock's financial analysis from the data the site holds: what the figures say in sentences, then the revenue
 * trend, the earnings trend and the valuation against the stock's own history.
 * Every sentence and figure is the backend's; nothing here computes one, and no AI writes any of it.
 */
export function AnalysisPanel({ stockId }: { stockId: string }) {
  const { t } = useTranslation('research')
  const analysis = useStockAnalysis(stockId)
  return (
    <Panel title={t('analysis.title')} description={t('analysis.question')} flush>
      {analysis.isPending && <Skeleton className="m-4 h-72 rounded-lg" />}
      {analysis.isError && <ErrorState error={analysis.error} title={t('analysis.failed')} onRetry={() => void analysis.refetch()} />}
      {analysis.data && (
        <div className="divide-y">
          <Readings analysis={analysis.data} />
          <div className="grid divide-y @4xl:grid-cols-2 @4xl:divide-x @4xl:divide-y-0">
            <Revenue revenue={analysis.data.revenue} />
            <Earnings earnings={analysis.data.earnings} />
          </div>
          <ValuationSection valuation={analysis.data.valuation} />
        </div>
      )}
    </Panel>
  )
}

function Section({ id, title, caption, children }: { id: string; title: string; caption?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="min-w-0 py-3.5">
      <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 px-4 md:px-5">
        <h3 id={id} className="text-sm font-semibold">
          {title}
        </h3>
        {caption && <p className="text-xs text-muted-foreground">{caption}</p>}
      </div>
      {children}
    </section>
  )
}

function Note({ children }: { children: ReactNode }) {
  return <p className="px-4 pt-2.5 text-xs text-pretty text-muted-foreground md:px-5">{children}</p>
}

/** The reading: one sentence per finding, in page order, each with what it counted. */
function Readings({ analysis }: { analysis: StockAnalysis }) {
  const { t } = useTranslation('research')
  const { short_months: short, long_months: long } = analysis.revenue
  return (
    <section aria-labelledby="analysis-reading" className="space-y-3 px-4 py-3.5 md:px-5">
      <h3 id="analysis-reading" className="text-sm font-semibold">
        {t('analysis.reading.title')}
      </h3>
      <ul className="grid gap-2 @2xl:grid-cols-2">
        {analysis.readings.map((reading) => {
          const { icon: Icon, tone } = READING_ICON[READING_TONE[reading.kind]]
          return (
            <li key={reading.kind} className="flex items-start gap-2.5 rounded-xl bg-muted/70 px-3 py-2.5 text-sm leading-relaxed">
              <Icon aria-hidden className={cn('mt-0.5 size-4 shrink-0', tone)} />
              <span className="min-w-0 text-pretty">
                {t(`analysis.reading.kind.${reading.kind}`, { count: reading.count ?? 0, short, long, needed: analysis.valuation.min_sessions })}
              </span>
            </li>
          )
        })}
      </ul>
      <p className="text-xs text-pretty text-muted-foreground">{t('analysis.reading.rules')}</p>
      <NotAdviceNote />
    </section>
  )
}

function Revenue({ revenue }: { revenue: StockAnalysis['revenue'] }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const months = revenue.months.slice(-MONTHS_SHOWN).reverse()
  const latest = months[0]
  if (!latest) {
    return (
      <Section id="analysis-revenue" title={t('analysis.revenue.title')}>
        <Note>{t('analysis.revenue.none')}</Note>
      </Section>
    )
  }
  const change = (value: number | null) => (value === null ? DASH : <ChangeValue value={value} format="percent" fractionDigits={1} />)
  const times = (value: number | null) => (value === null ? DASH : `×${format.number(value, 2)}`)
  const columns: Column<RevenueMonth>[] = [
    { key: 'month', header: t('analysis.revenue.month'), cell: (month) => format.yearMonth(month.year, month.month) },
    { key: 'revenue', header: t('analysis.revenue.revenue'), numeric: true, cell: (month) => (month.revenue === null ? DASH : format.compact(month.revenue * 1000)) },
    { key: 'yoy', header: t('analysis.yearOverYear'), numeric: true, cell: (month) => change(month.year_over_year) },
    { key: 'acceleration', header: t('analysis.revenue.acceleration'), numeric: true, cell: (month) => times(month.acceleration) },
  ]
  return (
    <Section
      id="analysis-revenue"
      title={t('analysis.revenue.title')}
      caption={t('analysis.revenue.caption', { month: format.yearMonth(latest.year, latest.month), date: format.date(latest.served_date) })}
    >
      <DataTable rows={months} columns={columns} rowKey={(month) => `${month.year}-${month.month}`} label={t('analysis.revenue.title')} className="border-t" />
      <Note>
        {t('analysis.revenue.explained', { short: revenue.short_months, long: revenue.long_months })}{' '}
        {latest.acceleration === null && t('analysis.revenue.short', { count: revenue.months.length, long: revenue.long_months })}
      </Note>
    </Section>
  )
}

function Earnings({ earnings }: { earnings: StockAnalysis['earnings'] }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const quarters = shownQuarters(earnings.quarters).slice(0, QUARTERS_SHOWN)
  if (quarters.length === 0) {
    return (
      <Section id="analysis-earnings" title={t('analysis.earnings.title')}>
        <Note>{t('analysis.earnings.none')}</Note>
      </Section>
    )
  }
  const money = (value: number | null) => (value === null ? DASH : format.number(value, 2))
  const share = (value: number | null) => (value === null ? DASH : `${format.number(value * 100, 1)}%`)
  const columns: Column<QuarterResult>[] = [
    { key: 'quarter', header: t('analysis.earnings.quarter'), cell: (quarter) => t('financials.quarter', quarter.quarter) },
    { key: 'own', header: t('analysis.earnings.quarterEps'), numeric: true, from: 'sm', cell: (quarter) => money(quarter.quarter_eps) },
    { key: 'ytd', header: t('analysis.earnings.yearToDate'), numeric: true, cell: (quarter) => money(quarter.eps_year_to_date) },
    {
      key: 'yoy',
      header: t('analysis.yearOverYear'),
      numeric: true,
      cell: (quarter) => (quarter.eps_year_over_year === null ? DASH : <ChangeValue value={quarter.eps_year_over_year} format="percent" fractionDigits={1} />),
    },
    { key: 'gross', header: t('analysis.earnings.grossMargin'), numeric: true, from: 'md', cell: (quarter) => share(quarter.gross_margin) },
    { key: 'operating', header: t('analysis.earnings.operatingMargin'), numeric: true, from: 'lg', cell: (quarter) => share(quarter.operating_margin) },
    { key: 'net', header: t('analysis.earnings.netMargin'), numeric: true, from: 'md', cell: (quarter) => share(quarter.net_margin) },
  ]
  const latest = quarters[0]!
  return (
    <Section id="analysis-earnings" title={t('analysis.earnings.title')} caption={t('analysis.earnings.caption', { count: quarters.length })}>
      <dl className="grid grid-cols-2 gap-3 px-4 pb-3 @md:grid-cols-3 md:px-5">
        <Stat label={t('analysis.earnings.latest', latest.quarter)} size="lg" className="col-span-2 @md:col-span-1">
          {money(latest.eps_year_to_date)}
        </Stat>
        <Stat label={t('analysis.earnings.grossMargin')}>{share(latest.gross_margin)}</Stat>
        <Stat label={t('analysis.earnings.debtRatio')}>{share(latest.debt_ratio)}</Stat>
      </dl>
      <DataTable
        rows={quarters}
        columns={columns}
        rowKey={(quarter) => `${quarter.quarter.year}-${quarter.quarter.quarter}`}
        label={t('analysis.earnings.title')}
        className="border-t"
      />
      <Note>
        {t('analysis.earnings.explained')}{' '}
        {earnings.filed_eps_fetched_at && t('analysis.earnings.filed', { date: format.date(earnings.filed_eps_fetched_at) })}
      </Note>
    </Section>
  )
}

function ValuationSection({ valuation }: { valuation: Valuation }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  if (valuation.session_date === null) {
    return (
      <Section id="analysis-valuation" title={t('analysis.valuation.title')}>
        <Note>{t('analysis.valuation.none')}</Note>
      </Section>
    )
  }
  const ratios: { key: 'pe' | 'pb' | 'yield'; standing: RatioStanding; unit: string }[] = [
    { key: 'pe', standing: valuation.pe_ratio, unit: '' },
    { key: 'pb', standing: valuation.pb_ratio, unit: '' },
    { key: 'yield', standing: valuation.dividend_yield, unit: '%' },
  ]
  return (
    <Section id="analysis-valuation" title={t('analysis.valuation.title')} caption={t('analysis.valuation.caption', { date: format.date(valuation.session_date) })}>
      <dl className="grid gap-3 px-4 @md:grid-cols-3 md:px-5">
        {ratios.map(({ key, standing, unit }) => (
          <div key={key} className="min-w-0 rounded-xl bg-muted/70 px-3 py-2.5">
            <Stat label={t(`analysis.valuation.ratio.${key}`)} size="lg">
              {standing.latest === null ? DASH : `${format.number(standing.latest, 2)}${unit}`}
            </Stat>
            <p className="mt-1 text-xs text-pretty text-muted-foreground">
              {standing.latest === null && key === 'pe'
                ? t('analysis.valuation.noPe')
                : standing.median === null
                  ? t('analysis.valuation.short', { count: standing.sessions, needed: valuation.min_sessions })
                  : t('analysis.valuation.median', { median: `${format.number(standing.median, 2)}${unit}`, count: standing.sessions })}
            </p>
          </div>
        ))}
      </dl>
      <Note>{t('analysis.valuation.explained', { first: valuation.first_session ? format.date(valuation.first_session) : DASH })}</Note>
    </Section>
  )
}

