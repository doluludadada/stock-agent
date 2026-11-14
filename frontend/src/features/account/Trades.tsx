import { ReceiptText } from 'lucide-react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { formatMonthDayTime, formatNumber, useFormat } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Panel } from '@/shared/ui/panel'
import { Skeleton } from '@/shared/ui/skeleton'
import { StateBlock } from '@/shared/ui/state-block'
import type { Trade, useTrades } from './api'

interface TradesPanelProps {
  trades: ReturnType<typeof useTrades>
  rows: Trade[] | undefined
  names: ReadonlyMap<string, string>
  /** The account's own words for the list: the mock account's trades, or the orders this site placed at a broker. */
  title: string
  description: string
  none: string
  className?: string
}

/** An account's filled orders, a page at a time, for the mock account and a real broker's alike. */
export function TradesPanel({ trades, rows, names, title, description, none, className }: TradesPanelProps) {
  const { t } = useTranslation('account')
  const more = trades.hasNextPage && (
    <Button type="button" variant="ghost" size="sm" className="w-full text-muted-foreground" disabled={trades.isFetchingNextPage} onClick={() => void trades.fetchNextPage()}>
      {t('trades.more')}
    </Button>
  )
  return (
    <Panel className={className} title={title} description={description} footer={more || undefined} flush>
      {trades.isPending && <Skeleton className="m-4 h-32 rounded-lg" />}
      {trades.isError && <ErrorState error={trades.error} title={t('trades.loadFailed')} onRetry={() => void trades.refetch()} />}
      {rows && (rows.length === 0 ? <StateBlock icon={ReceiptText} title={none} /> : <TradesTable rows={rows} names={names} label={title} />)}
    </Panel>
  )
}

/** Each fill with the run whose decision it carried out; one that came through a follow says so. */
function TradesTable({ rows, names, label }: { rows: Trade[]; names: ReadonlyMap<string, string>; label: string }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const format = useFormat()
  const side = (trade: Trade) => t(`runs:action.${trade.order.action}`)
  const price = (trade: Trade) => (trade.order.average_filled_price === null ? '—' : format.price(trade.order.average_filled_price))
  const columns: Column<Trade>[] = [
    { key: 'time', header: t('trades.column.time'), from: 'md', className: 'tabular whitespace-nowrap text-muted-foreground', cell: ({ order }) => formatMonthDayTime(locale, order.created_at) },
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0',
      cell: (trade) => (
        <Link to={paths.stock(trade.order.stock_id)} className="flex min-h-11 min-w-0 flex-col justify-center hover:text-brand focus-visible:text-brand md:min-h-0">
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="truncate font-medium">{names.get(trade.order.stock_id) ?? trade.order.stock_id}</span>
            <span className="shrink-0 font-mono text-xs text-muted-foreground">{trade.order.stock_id}</span>
          </span>
          <span className="tabular truncate text-xs text-muted-foreground md:hidden">
            {t('trades.line', { side: side(trade), shares: formatNumber(locale, trade.order.filled_quantity), price: price(trade), time: formatMonthDayTime(locale, trade.order.created_at) })}
          </span>
        </Link>
      ),
    },
    { key: 'side', header: t('trades.column.side'), from: 'md', className: 'whitespace-nowrap', cell: side },
    { key: 'shares', header: t('trades.column.shares'), numeric: true, from: 'md', cell: ({ order }) => formatNumber(locale, order.filled_quantity) },
    { key: 'price', header: t('trades.column.price'), numeric: true, from: 'md', cell: price },
    { key: 'costs', header: t('trades.column.costs'), numeric: true, from: 'lg', cell: ({ order }) => formatNumber(locale, order.fee + order.tax) },
    {
      key: 'realized',
      header: t('trades.column.realized'),
      numeric: true,
      from: 'sm',
      cell: ({ order }) => (order.realized_pnl === null ? '—' : <ChangeValue value={order.realized_pnl} format="absolute" fractionDigits={0} />),
    },
    { key: 'source', header: t('trades.column.source'), cell: (trade) => <SourceRun trade={trade} /> },
  ]
  return <DataTable rows={rows} columns={columns} rowKey={(trade) => trade.order.id} label={label} />
}

/** The run whose decision the trade carried out: for a follow's order, the run it followed. */
function SourceRun({ trade }: { trade: Trade }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const followed = trade.order.run_id !== trade.run.run_id
  return (
    <span className="flex flex-col items-start sm:flex-row sm:items-center sm:gap-2">
      <Link to={paths.run(trade.run.run_id)} className="inline-flex min-h-11 items-center whitespace-nowrap hover:text-brand focus-visible:text-brand md:min-h-0">
        {t('trades.source', { workflow: t(`runs:workflow.${trade.run.workflow}`), time: formatMonthDayTime(locale, trade.run.start_time) })}
      </Link>
      {followed && (
        <Badge variant="outline" className="font-normal">
          {t('trades.followed')}
        </Badge>
      )}
    </span>
  )
}
