import { ArrowRight, CopyCheck, FlaskConical, Landmark, LineChart, ReceiptText, Wallet } from 'lucide-react'
import { lazy, Suspense, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { useListedNames } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { directionOf } from '@/shared/lib/direction'
import { formatCompact, formatDateTime, formatMonthDayTime, formatNumber, useFormat } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { Input } from '@/shared/ui/input'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { RequireSignIn } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { StackedBar } from '@/shared/ui/stacked-bar'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { useAccountHistory, useTrades, type AccountHistory, type Trade } from './api'
import { equityPoints, holdings, moveBetween, totalReturn, unrealizedRatio, type AccountValue, type EquityPoint, type Holding } from './model'

const ValueChart = lazy(() => import('@/shared/ui/value-chart').then((module) => ({ default: module.ValueChart })))

const percent = (locale: string, ratio: number) => `${formatNumber(locale, ratio * 100, 1)}%`

export function AccountPage() {
  const { t } = useTranslation('account')
  return (
    <div className="space-y-5 lg:space-y-6">
      <PageHeader eyebrow={t('common:nav.section.mine')} title={t('title')} description={t('description')} />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <Account />
      </RequireSignIn>
    </div>
  )
}

/**
 * The account as one desk: the equity leads; the equity curve beside the allocation from 1280 px; the positions and
 * the trades across; the past-day lookup beside what this account is. Narrower, the same order in one column. A mock
 * account with no position and no trade says how to fill it instead of listing nothing.
 */
function Account() {
  const { t } = useTranslation('account')
  const [asOf, setAsOf] = useState<string | null>(null)
  const history = useAccountHistory(asOf)
  const trades = useTrades()
  const positions = history.data?.current.positions
  const tradeRows = useMemo(() => trades.data?.pages.flatMap((page) => page.trades), [trades.data])
  const codes = useMemo(
    () => [...new Set([...(positions ?? []).map((position) => position.stock_id), ...(tradeRows ?? []).map((trade) => trade.order.stock_id)])],
    [positions, tradeRows],
  )
  const names = useListedNames(codes)
  if (history.isPending) return <Skeleton className="h-96 rounded-2xl" />
  if (history.isError) return <ErrorState error={history.error} title={t('loadFailed')} onRetry={() => void history.refetch()} className="rounded-2xl border bg-card py-12" />
  const { data } = history
  const empty = data.opening !== null && data.current.positions.length === 0 && tradeRows?.length === 0
  return (
    <div className="grid items-start gap-4 md:grid-cols-2 lg:gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <Summary history={data} className="md:col-span-2" />
      {empty && <GetStarted className="md:col-span-2" />}
      <EquityPanel history={data} className="md:col-span-2 xl:col-span-1" />
      <AllocationPanel value={data.current} names={names} className="md:col-span-2 xl:col-span-1" />
      <Positions value={data.current} liveStockIds={data.live_stock_ids} names={names} className="md:col-span-2" />
      {!empty && <TradesPanel trades={trades} rows={tradeRows} names={names} className="md:col-span-2" />}
      <AsOfPanel history={data} asOf={asOf} onAsOf={setAsOf} busy={history.isFetching} />
      <AboutPanel history={data} />
    </div>
  )
}

function Summary({ history, className }: { history: AccountHistory; className?: string }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const format = useFormat()
  const value = history.current
  const points = useMemo(() => equityPoints(history), [history])
  const today = moveBetween(points.at(-2), points.at(-1))
  const since = moveBetween(points[0], points.at(-1))
  const total = totalReturn(history)
  return (
    <Panel className={className}>
      <div className="grid gap-x-8 gap-y-5 @4xl:grid-cols-[auto_minmax(0,1fr)] @4xl:items-end">
        <div className="min-w-0 space-y-1.5">
          <p className="text-xs text-muted-foreground">{t('value.equity')}</p>
          <p className="figure">{formatNumber(locale, value.equity)}</p>
          {total && (
            <p className="flex flex-wrap items-center gap-1.5 text-sm">
              <span className="text-muted-foreground">{t('summary.total')}</span>
              <ChangeValue value={total.profit} format="absolute" fractionDigits={0} arrow />
              <ChangeValue value={total.ratio} format="percent" pill />
            </p>
          )}
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {today && (
              <span className="flex items-center gap-1.5">
                {t('summary.today')}
                <ChangeValue value={today.change} format="absolute" fractionDigits={0} arrow />
                <ChangeValue value={today.ratio} format="percent" pill />
              </span>
            )}
            {!total && since && points[0] && (
              <span className="flex items-center gap-1.5">
                {t('summary.since', { date: format.monthDay(points[0].date) })}
                <ChangeValue value={since.ratio} format="percent" />
              </span>
            )}
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 @xl:grid-cols-[repeat(auto-fit,minmax(8rem,1fr))] @4xl:border-l @4xl:pl-8">
          {history.opening && (
            <Stat size="lg" label={t('summary.startingCapital')}>
              {formatNumber(locale, history.opening.initial_cash)}
              <span className="block text-xs font-normal text-muted-foreground">{t('summary.since', { date: format.monthDay(history.opening.opened_at) })}</span>
            </Stat>
          )}
          <Stat size="lg" label={t('value.unrealized')}>
            <ChangeValue value={value.unrealized_pnl} format="absolute" fractionDigits={0} />
            <span className="ml-1.5 text-xs font-normal">
              <ChangeValue value={unrealizedRatio(value)} format="percent" />
            </span>
          </Stat>
          <Stat size="lg" label={t('value.cash')}>
            {formatNumber(locale, value.cash)}
          </Stat>
          <Stat size="lg" label={t('value.marketValue')}>
            {formatNumber(locale, value.market_value)}
          </Stat>
          <Stat size="lg" label={t('summary.positions')}>
            {t('summary.count', { count: value.positions.length })}
          </Stat>
        </dl>
      </div>
    </Panel>
  )
}

function EquityPanel({ history, className }: { history: AccountHistory; className?: string }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const format = useFormat()
  const points = useMemo(() => equityPoints(history), [history])
  const first = points[0]
  const last = points.at(-1)
  const extremes = useMemo(() => {
    const sorted = [...points].sort((a, b) => a.value - b.value)
    return { low: sorted[0], high: sorted.at(-1) }
  }, [points])
  const day = (point: EquityPoint | undefined) => point && <span className="block text-xs font-normal text-muted-foreground">{format.monthDay(point.date)}</span>

  return (
    <Panel
      className={className}
      title={t('curveTitle')}
      description={t('curveQuestion')}
      aside={first && last && <span className="tabular">{format.monthDay(first.date)} – {format.monthDay(last.date)}</span>}
    >
      {!first || !last ? (
        <StateBlock icon={LineChart} title={t('noCurve')} description={t('noCurveHint')} />
      ) : (
        <div className="space-y-4">
          <Suspense fallback={<Skeleton className="h-(--chart-price-height) rounded-xl" />}>
            <ValueChart
              data={points}
              direction={directionOf(last.value - first.value)}
              label={t('curveLabel')}
              formatValue={(value) => formatNumber(locale, value)}
              formatAxisValue={(value) => formatCompact(locale, value)}
              formatAxisDate={format.monthDay}
              formatTooltipDate={(date) => format.date(date, 'long')}
            />
          </Suspense>
          <dl className="grid grid-cols-3 gap-4 border-t pt-4">
            <Stat label={t('curve.start')}>
              {formatNumber(locale, first.value)}
              {day(first)}
            </Stat>
            <Stat label={t('curve.high')}>
              {extremes.high && formatNumber(locale, extremes.high.value)}
              {day(extremes.high)}
            </Stat>
            <Stat label={t('curve.low')}>
              {extremes.low && formatNumber(locale, extremes.low.value)}
              {day(extremes.low)}
            </Stat>
          </dl>
        </div>
      )}
    </Panel>
  )
}

/** Stocks against cash as one bar, then each position's share of the equity as a ranked bar list in one hue. */
function AllocationPanel({ value, names, className }: { value: AccountValue; names: ReadonlyMap<string, string>; className?: string }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const rows = useMemo(() => holdings(value), [value])
  const stocks = value.equity ? value.market_value / value.equity : 0
  const cash = value.equity ? value.cash / value.equity : 0
  const widest = Math.max(...rows.map((row) => row.weight), 0)

  return (
    <Panel className={className} title={t('allocation.title')} description={t('allocation.question')}>
      <div className="space-y-4">
        <div className="space-y-2">
          <StackedBar
            className="h-2.5"
            label={t('allocation.bar', { stocks: percent(locale, stocks), cash: percent(locale, cash) })}
            segments={[
              { key: 'stocks', value: value.market_value, className: 'bg-brand' },
              { key: 'cash', value: Math.max(value.cash, 0), className: 'bg-faint/40' },
            ]}
          />
          <p className="tabular flex justify-between text-xs">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="size-2 rounded-full bg-brand" />
              {t('allocation.stocks')} {percent(locale, stocks)}
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="size-2 rounded-full bg-faint/40" />
              {t('allocation.cash')} {percent(locale, cash)}
            </span>
          </p>
        </div>
        {rows.length > 0 && (
          <div className="space-y-2.5 border-t pt-4">
            <p className="text-xs text-muted-foreground">{t('allocation.holdings')}</p>
            <ul className="space-y-2.5">
              {rows.map((row) => (
                <li key={row.stock_id} className="grid grid-cols-[minmax(0,1fr)_3.5rem] items-center gap-x-3 gap-y-1 text-sm">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate">{names.get(row.stock_id) ?? row.stock_id}</span>
                    <span className="font-mono text-xs text-muted-foreground">{row.stock_id}</span>
                  </span>
                  <span className="tabular text-right">{percent(locale, row.weight)}</span>
                  <span aria-hidden className="col-span-2 h-1.5 overflow-hidden rounded-full bg-muted">
                    <span className="block h-full rounded-full bg-brand/70" style={{ width: `${widest ? (row.weight / widest) * 100 : 0}%` }} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  )
}

interface PositionsProps {
  value: AccountValue
  liveStockIds: readonly string[]
  names: ReadonlyMap<string, string>
  className?: string
}

function Positions({ value, liveStockIds, names, className }: PositionsProps) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const format = useFormat()
  const rows = useMemo(() => holdings(value), [value])
  const live = new Set(liveStockIds)
  const columns: Column<Holding>[] = [
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <Link to={paths.stock(row.stock_id)} className="stretched-link flex min-w-0 items-baseline gap-2 hover:text-brand focus-visible:text-brand">
          <span className="truncate font-medium" title={names.get(row.stock_id)}>
            {names.get(row.stock_id) ?? row.stock_id}
          </span>
          <span className="shrink-0 font-mono text-xs text-muted-foreground">{row.stock_id}</span>
        </Link>
      ),
    },
    { key: 'quantity', header: t('column.quantity'), numeric: true, from: 'md', cell: (row) => formatNumber(locale, row.quantity) },
    { key: 'cost', header: t('column.averageCost'), numeric: true, from: 'md', cell: (row) => format.price(row.average_cost) },
    { key: 'price', header: t('column.markPrice'), numeric: true, from: 'sm', cell: (row) => format.price(row.mark_price) },
    {
      key: 'marked',
      header: t('column.markedAt'),
      from: 'xl',
      cell: (row) => (
        <span className="text-xs whitespace-nowrap text-muted-foreground">
          {!row.marked_at
            ? t('unpriced')
            : live.has(row.stock_id)
              ? t('realtime', { time: formatMonthDayTime(locale, row.marked_at) })
              : t('dailyClose', { date: format.monthDay(row.marked_at) })}
        </span>
      ),
    },
    { key: 'value', header: t('column.marketValue'), numeric: true, cell: (row) => formatNumber(locale, row.market_value) },
    {
      key: 'pnl',
      header: t('column.unrealized'),
      numeric: true,
      cell: (row) => (
        <span className="flex flex-col items-end leading-tight sm:flex-row sm:items-baseline sm:justify-end sm:gap-2">
          <ChangeValue value={row.unrealized_pnl} format="absolute" fractionDigits={0} />
          <ChangeValue value={row.returnRatio} format="percent" className="text-xs" />
        </span>
      ),
    },
    { key: 'weight', header: t('column.weight'), numeric: true, from: 'lg', cell: (row) => <span className="text-muted-foreground">{percent(locale, row.weight)}</span> },
  ]

  return (
    <Panel className={className} title={t('positionsTitle')} description={rows.length > 0 ? t('positionsSorted', { count: rows.length }) : undefined} flush>
      {rows.length === 0 ? <StateBlock icon={Wallet} title={t('noPositions')} /> : <DataTable rows={rows} columns={columns} rowKey={(row) => row.stock_id} label={t('positionsTitle')} />}
    </Panel>
  )
}

/** What fills an empty mock account: following a finished analysis, with the way to the runs. */
function GetStarted({ className }: { className?: string }) {
  const { t } = useTranslation('account')
  return (
    <Panel className={className}>
      <StateBlock
        icon={CopyCheck}
        title={t('start.title')}
        description={t('start.description')}
        action={
          <Button asChild>
            <Link to={paths.runs}>
              {t('start.link')}
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        }
      />
    </Panel>
  )
}

interface TradesPanelProps {
  trades: ReturnType<typeof useTrades>
  rows: Trade[] | undefined
  names: ReadonlyMap<string, string>
  className?: string
}

function TradesPanel({ trades, rows, names, className }: TradesPanelProps) {
  const { t } = useTranslation('account')
  const more = trades.hasNextPage && (
    <Button type="button" variant="ghost" size="sm" className="w-full text-muted-foreground" disabled={trades.isFetchingNextPage} onClick={() => void trades.fetchNextPage()}>
      {t('trades.more')}
    </Button>
  )
  return (
    <Panel className={className} title={t('trades.title')} description={t('trades.question')} footer={more || undefined} flush>
      {trades.isPending && <Skeleton className="m-4 h-32 rounded-lg" />}
      {trades.isError && <ErrorState error={trades.error} title={t('trades.loadFailed')} onRetry={() => void trades.refetch()} />}
      {rows && (rows.length === 0 ? <StateBlock icon={ReceiptText} title={t('trades.none')} /> : <TradesTable rows={rows} names={names} />)}
    </Panel>
  )
}

/** Each fill with the run whose decision it carried out; one that came through a follow says so. */
function TradesTable({ rows, names }: { rows: Trade[]; names: ReadonlyMap<string, string> }) {
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
  return <DataTable rows={rows} columns={columns} rowKey={(trade) => trade.order.id} label={t('trades.title')} />
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

function AsOfPanel({ history, asOf, onAsOf, busy }: { history: AccountHistory; asOf: string | null; onAsOf: (date: string | null) => void; busy: boolean }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const [draft, setDraft] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onAsOf(/^\d{4}-\d{2}-\d{2}$/.test(draft) ? draft : null)
  }
  return (
    <Panel title={t('asOfLabel')} description={t('asOfQuestion')}>
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
        <Input type="date" value={draft} onChange={(event) => setDraft(event.target.value)} aria-label={t('asOfLabel')} className="w-44" />
        <Button type="submit" variant="outline" disabled={busy}>
          {t('asOfShow')}
        </Button>
      </form>
      <div className="mt-4">
        {!asOf ? (
          <p className="text-sm text-muted-foreground">{t('asOfHint')}</p>
        ) : history.as_of ? (
          <div className="space-y-3">
            <p className="tabular text-xs text-muted-foreground">{t('asOfTitle', { time: formatDateTime(locale, history.as_of.last_fill_at) })}</p>
            <dl className="grid grid-cols-2 gap-4 @xl:grid-cols-4">
              <Stat label={t('value.equity')}>{formatNumber(locale, history.as_of.value.equity)}</Stat>
              <Stat label={t('value.cash')}>{formatNumber(locale, history.as_of.value.cash)}</Stat>
              <Stat label={t('value.marketValue')}>{formatNumber(locale, history.as_of.value.market_value)}</Stat>
              <Stat label={t('value.unrealized')}>
                <ChangeValue value={history.as_of.value.unrealized_pnl} format="absolute" fractionDigits={0} />
              </Stat>
            </dl>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t('asOfNone', { date: asOf })}</p>
        )}
      </div>
    </Panel>
  )
}

/** Which broker keeps the account and how orders go, said once instead of above every figure. */
function AboutPanel({ history }: { history: AccountHistory }) {
  const { t } = useTranslation('account')
  const mock = history.execution_provider === 'mock'
  const Icon = mock ? FlaskConical : Landmark
  return (
    <Panel title={t('about.title')}>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-6 gap-y-3 text-sm">
        <dt className="text-muted-foreground">{t('about.broker')}</dt>
        <dd>
          <Badge variant="outline" className="gap-1 border-gold/40 font-normal text-gold">
            <Icon aria-hidden className="size-3" />
            {t(`provider.${history.execution_provider}`)}
          </Badge>
        </dd>
        <dt className="text-muted-foreground">{t('about.orderMode')}</dt>
        <dd>{t(`orderMode.${history.order_mode}`)}</dd>
      </dl>
      <p className="mt-4 border-t pt-4 text-sm text-pretty text-muted-foreground">{t(mock ? 'mockNotice' : 'brokerNotice')}</p>
    </Panel>
  )
}
