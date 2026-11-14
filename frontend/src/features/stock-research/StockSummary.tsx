import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'
import { useLocale, useTranslation } from '@/i18n'
import { useShows } from '@/shared/api'
import { formatSignedPercent, useFormat } from '@/shared/lib/format'
import { ChangeValue } from '@/shared/ui/change-value'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { RankingScore, RankingScoreNote } from '@/shared/ui/ranking-score'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { useStockAnalysis, useStockRanking, type StockAnalysis } from './api'
import { SECTION_ANCHORS } from './brief'
import { chartMonths, type RevenueMonth } from './model'

const DASH = '—'

/**
 * The first thing a stock's page answers: how its revenue is doing and what the monthly ranking scores it. Both read
 * held data only. On a phone the score comes first, since it is one figure; from 1280 px the revenue takes the wider
 * column beside it. The score is the ranking's, so a viewer the site does not show the ranking to gets the revenue
 * alone, and the score is never asked for.
 */
export function StockSummary({ stockId }: { stockId: string }) {
  const scored = useShows('ranking')
  if (!scored) {
    return (
      <div id={SECTION_ANCHORS.revenue}>
        <RevenuePanel stockId={stockId} />
      </div>
    )
  }
  return (
    <div className="card-grid xl:grid-cols-12">
      <div id={SECTION_ANCHORS.ranking} className="min-w-0 xl:order-last xl:col-span-4">
        <ScorePanel stockId={stockId} />
      </div>
      <div id={SECTION_ANCHORS.revenue} className="min-w-0 xl:col-span-8">
        <RevenuePanel stockId={stockId} />
      </div>
    </div>
  )
}

function ScorePanel({ stockId }: { stockId: string }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const ranking = useStockRanking(stockId)
  const decided = ranking.data
    ? t('score.decided', {
        date: format.date(ranking.data.decided_on),
        month: format.yearMonth(Number(ranking.data.revenue_month.slice(0, 4)), Number(ranking.data.revenue_month.slice(5, 7))),
      })
    : t('score.question')
  return (
    <Panel title={t('score.title')} description={decided}>
      {ranking.isPending && (
        <div className="space-y-2">
          <Skeleton className="h-28 rounded-lg" />
          <p className="text-xs text-pretty text-muted-foreground">{t('score.loading')}</p>
        </div>
      )}
      {ranking.isError && <p className="text-sm text-pretty text-muted-foreground">{t('score.unavailable')}</p>}
      {ranking.data && <RankingScore standing={ranking.data} />}
      <RankingScoreNote className="mt-4 border-t pt-3" />
    </Panel>
  )
}

function RevenuePanel({ stockId }: { stockId: string }) {
  const { t } = useTranslation('research')
  const analysis = useStockAnalysis(stockId)
  return (
    <Panel title={t('revenue.title')} description={t('revenue.question')}>
      {analysis.isPending && <Skeleton className="h-64 rounded-lg" />}
      {analysis.isError && <ErrorState error={analysis.error} title={t('analysis.failed')} onRetry={() => void analysis.refetch()} />}
      {analysis.data && <Revenue revenue={analysis.data.revenue} />}
    </Panel>
  )
}

function Revenue({ revenue }: { revenue: StockAnalysis['revenue'] }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const latest = revenue.months.at(-1)
  if (!latest) return <p className="text-sm text-pretty text-muted-foreground">{t('analysis.revenue.none')}</p>
  const months = chartMonths(revenue.months)
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 @md:grid-cols-3">
        <Stat label={t('revenue.latest', { month: format.yearMonth(latest.year, latest.month) })} size="lg" className="col-span-2 @md:col-span-1">
          {latest.revenue === null ? DASH : format.compact(latest.revenue * 1000)}
        </Stat>
        <Stat label={t('analysis.yearOverYear')} size="lg">
          {latest.year_over_year === null ? DASH : <ChangeValue value={latest.year_over_year} format="percent" fractionDigits={1} arrow />}
        </Stat>
        <Stat label={t('revenue.acceleration', { short: revenue.short_months, long: revenue.long_months })} size="lg">
          {latest.acceleration === null ? DASH : `×${format.number(latest.acceleration, 2)}`}
        </Stat>
      </dl>
      {months.length > 1 && <RevenueChart months={months} />}
      <p className="text-xs leading-relaxed text-pretty text-muted-foreground">
        {t('revenue.held', { count: revenue.months.length, date: format.date(latest.served_date) })}{' '}
        {latest.acceleration === null && t('analysis.revenue.short', { count: revenue.months.length, long: revenue.long_months })}
      </p>
    </div>
  )
}

/** Each held month's revenue as a bar, up to three years, with the month, the revenue and its change on hover or touch. */
function RevenueChart({ months }: { months: RevenueMonth[] }) {
  const { t } = useTranslation('research')
  const locale = useLocale()
  const format = useFormat()
  const rows = months.map((month) => ({ ...month, label: `${month.year}-${String(month.month).padStart(2, '0')}`, amount: (month.revenue ?? 0) * 1000 }))
  const tooltip = (props: TooltipContentProps<ValueType, NameType>) => {
    const month = props.payload?.[0]?.payload as (typeof rows)[number] | undefined
    if (!props.active || !month) return null
    return (
      <div className="min-w-40 rounded-lg border bg-popover px-3 py-2 text-xs shadow-pop">
        <div className="mb-1 font-medium text-foreground">{format.yearMonth(month.year, month.month)}</div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">{t('analysis.revenue.revenue')}</span>
          <span className="tabular font-medium text-foreground">{month.revenue === null ? DASH : format.compact(month.amount)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">{t('analysis.yearOverYear')}</span>
          <span className="tabular font-medium text-foreground">{month.year_over_year === null ? DASH : formatSignedPercent(locale, month.year_over_year, 1)}</span>
        </div>
      </div>
    )
  }
  return (
    <figure className="m-0">
      <figcaption className="sr-only">{t('revenue.chart', { count: months.length })}</figcaption>
      <div aria-hidden className="h-40 w-full md:h-52">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 0, bottom: 0, left: 0 }} barCategoryGap="18%">
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis
              dataKey="label"
              tickFormatter={(label: string) => label.slice(2).replace('-', '/')}
              tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
              minTickGap={24}
            />
            <YAxis orientation="right" tickFormatter={(value: number) => format.compact(value)} tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} axisLine={false} tickLine={false} width={52} tickCount={4} />
            <Tooltip content={tooltip} cursor={{ fill: 'var(--chart-grid)' }} isAnimationActive={false} />
            <Bar dataKey="amount" fill="var(--chart-price)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
