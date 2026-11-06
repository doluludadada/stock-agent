import { FileSpreadsheet } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { useStockFinancials, type StockFinancials } from './api'
import { QUARTER_FIGURES, type QuarterFigure, type QuarterFinancials } from './model'

/** A year of quarters; a phone shows the latest two and a tablet three, since the figures' names take the first column. */
const QUARTERS_SHOWN = 4
const QUARTER_SHOWN_FROM = [undefined, undefined, 'md', 'lg'] as const

type MonthlyRevenue = StockFinancials['monthly_revenues'][number]

/** A dash wherever the company's industry format reports no such figure. */
const DASH = '—'

/** The stock's archived quarters and its latest month's revenue, as the exchanges' open data served them. */
export function FinancialsPanel({ stockId }: { stockId: string }) {
  const { t } = useTranslation('research')
  const financials = useStockFinancials(stockId)
  return (
    <Panel title={t('financials.title')} description={t('financials.question')} flush>
      {financials.isPending && <Skeleton className="m-4 h-56 rounded-lg" />}
      {financials.isError && <ErrorState error={financials.error} title={t('financials.failed')} onRetry={() => void financials.refetch()} />}
      {financials.data && <Financials financials={financials.data} />}
    </Panel>
  )
}

function Financials({ financials }: { financials: StockFinancials }) {
  const { t } = useTranslation('research')
  const month = financials.monthly_revenues.at(-1)
  const quarters = financials.quarters.slice(-QUARTERS_SHOWN).reverse()
  if (!month && quarters.length === 0) {
    return <StateBlock icon={FileSpreadsheet} title={t('financials.none.title')} description={t('financials.none.description')} />
  }
  return (
    <div className="divide-y">
      {month && <LatestMonth revenue={month} />}
      {quarters.length > 0 && <Quarters quarters={quarters} />}
    </div>
  )
}

function LatestMonth({ revenue }: { revenue: MonthlyRevenue }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const change = (percent: number | null) => (percent === null ? DASH : <ChangeValue value={percent / 100} format="percent" />)
  return (
    <section aria-labelledby="latest-month-revenue" className="space-y-2 px-4 py-3.5 md:px-5">
      <h3 id="latest-month-revenue" className="text-xs font-medium text-muted-foreground">
        {t('financials.month', { month: format.yearMonth(revenue.year, revenue.month) })}
      </h3>
      <dl className="grid grid-cols-3 gap-3">
        <Stat label={t('financials.revenue')} size="lg">
          {revenue.revenue === null ? DASH : format.compact(revenue.revenue * 1000)}
        </Stat>
        <Stat label={t('financials.monthOverMonth')}>{change(revenue.month_over_month_percent)}</Stat>
        <Stat label={t('financials.yearOverYear')}>{change(revenue.year_over_year_percent)}</Stat>
      </dl>
    </section>
  )
}

function Quarters({ quarters }: { quarters: QuarterFinancials[] }) {
  const { t } = useTranslation('research')
  const format = useFormat()
  const figure = (quarter: QuarterFinancials, item: QuarterFigure) => {
    const value = quarter[item.key]
    if (value === null || value === undefined) return DASH
    return item.unit === 'amount' ? format.compact(value * 1000) : format.number(value, 2)
  }
  const columns: Column<QuarterFigure>[] = [
    { key: 'figure', header: t('financials.column.figure'), className: 'w-full', cell: (item) => t(`financials.figure.${item.key}`) },
    ...quarters.map((quarter, index) => ({
      key: `${quarter.quarter.year}-${quarter.quarter.quarter}`,
      header: t('financials.quarter', { year: quarter.quarter.year, quarter: quarter.quarter.quarter }),
      numeric: true,
      from: QUARTER_SHOWN_FROM[index],
      cell: (item: QuarterFigure) => figure(quarter, item),
    })),
  ]
  return (
    <div>
      <DataTable rows={QUARTER_FIGURES} columns={columns} rowKey={(item) => item.key} label={t('financials.quartersLabel')} />
      <p className="border-t px-4 py-2.5 text-xs text-pretty text-muted-foreground md:px-5">{t('financials.units')}</p>
    </div>
  )
}
