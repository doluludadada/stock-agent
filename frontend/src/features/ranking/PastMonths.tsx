import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useTranslation } from '@/i18n'
import { DASH, useFormat } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { StockChip } from '@/shared/ui/stock-name'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/ui/dialog'
import { Panel } from '@/shared/ui/panel'
import { ShowMore } from '@/shared/ui/show-more'
import { monthHoldings, monthRows, stockNames, type MonthRow, type RankingBacktest } from './model'
import { RankedStocksTable } from './RankedStocksTable'

const MONTHS_SHOWN = 12
/** The address parameter that names the decision whose stocks are open. */
const MONTH_PARAM = 'month'

/**
 * Every decision of the backtest on screen, newest first, with what holding it did until the next one. A row opens
 * that month's ranking and holdings; the address names it, so it can be reloaded and gone back from.
 */
export function PastMonths({ backtest, className }: { backtest: RankingBacktest; className?: string }) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const tableId = useId()
  const [params, setParams] = useSearchParams()
  const [expanded, setExpanded] = useState(false)
  const rows = useMemo(() => monthRows(backtest), [backtest])
  const names = useMemo(() => stockNames(backtest.rankings), [backtest.rankings])
  const openIndex = rows.findIndex((row) => row.ranking.decided_on === params.get(MONTH_PARAM))
  const hrefOf = (row: MonthRow | undefined) => {
    if (!row) return null
    const next = new URLSearchParams(params)
    next.set(MONTH_PARAM, row.ranking.decided_on)
    return `?${next}`
  }
  const close = () => {
    const next = new URLSearchParams(params)
    next.delete(MONTH_PARAM)
    setParams(next)
  }
  const month = (date: string) => {
    const [year, monthNumber] = date.split('-').map(Number) as [number, number]
    return format.yearMonth(year, monthNumber)
  }
  const result = (value: number | null) => (value === null ? <span className="text-muted-foreground">{DASH}</span> : <ChangeValue value={value} format="percent" fractionDigits={1} />)

  const columns: Column<MonthRow>[] = [
    {
      key: 'decided',
      header: t('months.column.decided'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <Link to={hrefOf(row)!} aria-label={t('months.open', { date: format.date(row.ranking.decided_on) })} className="stretched-link flex min-h-11 min-w-0 flex-col justify-center hover:text-brand focus-visible:text-brand md:min-h-0">
          <span className="flex min-w-0 items-center gap-2">
            <span className="tabular font-medium">{format.date(row.ranking.decided_on)}</span>
            {row.current && (
              <Badge variant="outline" className="border-primary/40 font-normal text-primary">
                {t('months.current')}
              </Badge>
            )}
          </span>
          <span className="truncate text-xs text-muted-foreground md:hidden">{row.held.length ? t('months.line', { count: row.held.length }) : t('months.cash')}</span>
        </Link>
      ),
    },
    { key: 'revenue', header: t('months.column.revenue'), from: 'md', className: 'whitespace-nowrap', cell: (row) => month(row.ranking.revenue_month) },
    { key: 'held', header: t('months.column.held'), numeric: true, from: 'md', cell: (row) => (row.held.length ? t('stocks', { count: row.held.length }) : <span className="text-muted-foreground">{t('months.cash')}</span>) },
    { key: 'until', header: t('months.column.until'), numeric: true, from: 'lg', cell: (row) => format.date(row.until) },
    { key: 'portfolio', header: t('series.ranking'), numeric: true, cell: (row) => result(row.portfolioReturn) },
    { key: 'benchmark', header: backtest.benchmark_id, numeric: true, cell: (row) => result(row.benchmarkReturn) },
    { key: 'open', header: t('months.column.open'), quietHeader: true, className: 'w-6 text-muted-foreground', cell: () => <ChevronRight aria-hidden className="size-4" /> },
  ]

  const open = rows[openIndex]
  return (
    <Panel
      className={className}
      flush
      title={t('months.title')}
      aside={<span className="tabular">{t('months.count', { count: rows.length })}</span>}
      footer={rows.length > MONTHS_SHOWN && <ShowMore expanded={expanded} onToggle={() => setExpanded(!expanded)} controls={tableId} moreLabel={t('months.more', { count: rows.length })} lessLabel={t('months.less')} />}
    >
      <DataTable id={tableId} rows={expanded ? rows : rows.slice(0, MONTHS_SHOWN)} columns={columns} rowKey={(row) => row.ranking.decided_on} label={t('months.title')} />
      <Dialog open={open !== undefined} onOpenChange={(next) => !next && close()}>
        {open && <MonthDialog row={open} benchmark={backtest.benchmark_id} names={names} olderHref={hrefOf(rows[openIndex + 1])} newerHref={hrefOf(rows[openIndex - 1])} />}
      </Dialog>
    </Panel>
  )
}

interface MonthDialogProps {
  row: MonthRow
  benchmark: string
  names: ReadonlyMap<string, string>
  olderHref: string | null
  newerHref: string | null
}

/** One decision: what it read, when it bought, how the month went against the benchmark, and the stocks it ranked and held. */
function MonthDialog({ row, benchmark, names, olderHref, newerHref }: MonthDialogProps) {
  const { t } = useTranslation('ranking')
  const format = useFormat()
  const { ranked, carried } = monthHoldings(row)
  const [year, monthNumber] = row.ranking.revenue_month.split('-').map(Number) as [number, number]
  const step = (href: string | null, label: string, icon: 'older' | 'newer') => {
    const className = 'inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-sm md:min-h-8'
    const content = (
      <>
        {icon === 'older' && <ChevronLeft aria-hidden className="size-4" />}
        {label}
        {icon === 'newer' && <ChevronRight aria-hidden className="size-4" />}
      </>
    )
    return href ? (
      <Link to={href} replace className={`${className} text-brand hover:bg-muted`}>
        {content}
      </Link>
    ) : (
      <span className={`${className} text-muted-foreground/60`}>
        {content}
      </span>
    )
  }
  return (
    <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col gap-0 p-0 sm:max-w-2xl">
      <DialogHeader className="gap-1.5 border-b pt-4 pr-16 pb-3 pl-4">
        <DialogTitle>{t('month.title', { date: format.date(row.ranking.decided_on) })}</DialogTitle>
        <DialogDescription className="text-pretty">
          {t('month.read', { month: format.yearMonth(year, monthNumber) })}{' '}
          {row.heldFrom ? t(row.current ? 'month.heldSince' : 'month.held', { from: format.date(row.heldFrom), until: format.date(row.until) }) : t('month.notYet')}
        </DialogDescription>
        {row.portfolioReturn !== null && (
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" data-testid="month-result">
            <span className="flex items-center gap-1.5">
              <span className="text-muted-foreground">{t('series.ranking')}</span>
              <ChangeValue value={row.portfolioReturn} format="percent" fractionDigits={1} />
            </span>
            {row.benchmarkReturn !== null && (
              <span className="flex items-center gap-1.5">
                <span className="text-muted-foreground">{benchmark}</span>
                <ChangeValue value={row.benchmarkReturn} format="percent" fractionDigits={1} />
              </span>
            )}
          </p>
        )}
      </DialogHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {ranked.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-pretty text-muted-foreground">{t(row.ranking.holds_cash ? 'month.cash' : 'month.none')}</p>
        ) : (
          <RankedStocksTable label={t('month.title', { date: format.date(row.ranking.decided_on) })} formula={row.ranking.formula} rows={ranked.map(({ stock, bought }) => ({ stock, mark: bought ? undefined : ('notBought' as const) }))} />
        )}
        {carried.length > 0 && (
          <div className="space-y-1.5 border-t px-4 py-3 text-sm">
            <p className="text-xs text-pretty text-muted-foreground">{t('month.carried')}</p>
            <ul className="flex flex-wrap gap-1.5">
              {carried.map((stockId) => (
                <li key={stockId}>
                  <StockChip stockId={stockId} name={names.get(stockId)} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <nav aria-label={t('month.step')} className="flex items-center justify-between border-t px-2 py-1.5">
        {step(olderHref, t('month.older'), 'older')}
        {step(newerHref, t('month.newer'), 'newer')}
      </nav>
    </DialogContent>
  )
}
