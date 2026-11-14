import { ArrowRight, CopyCheck, FlaskConical, LineChart, Wallet } from 'lucide-react'
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
import { PageSkeleton, Skeleton } from '@/shared/ui/skeleton'
import { StackedBar } from '@/shared/ui/stacked-bar'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { useAccountHistory, useTrades, type AccountHistory } from './api'
import { TradesPanel } from './Trades'
import { equityPoints, holdings, moveBetween, totalReturn, unrealizedRatio, type AccountValue, type EquityPoint, type Holding } from './model'

const ValueChart = lazy(() => import('@/shared/ui/value-chart').then((module) => ({ default: module.ValueChart })))

const percent = (locale: string, ratio: number) => `${formatNumber(locale, ratio * 100, 1)}%`

/** The mock account: play money a finished run's decisions are followed into. A real broker's account has its own page. */
export function AccountPage() {
  const { t } = useTranslation('account')
  return (
    <div className="page-stack">
      <PageHeader title={t('page.mock.title')} description={t('page.mock.description')} />
      <RequireSignIn layout="page" reason={t('signIn')}>
        <Account />
      </RequireSignIn>
    </div>
  )
}

/**
 * The account as one desk: the equity leads; the equity curve beside the allocation from 1280 px; the positions and
 * the trades across; the past-day lookup beside what this account is. Narrower, the same order in one column. An
 * account with no position and no trade says how to fill it instead of listing nothing.
 */
function Account() {
  const { t } = useTranslation('account')
  const history = useAccountHistory(null)
  const trades = useTrades('mock')
  const positions = history.data?.current.positions
  const tradeRows = useMemo(() => trades.data?.pages.flatMap((page) => page.trades), [trades.data])
  const codes = useMemo(
    () => [...new Set([...(positions ?? []).map((position) => position.stock_id), ...(tradeRows ?? []).map((trade) => trade.order.stock_id)])],
    [positions, tradeRows],
  )
  const names = useListedNames(codes)
  if (history.isPending) return <PageSkeleton />
  if (history.isError) return <ErrorState error={history.error} title={t('loadFailed')} onRetry={() => void history.refetch()} framed />
  const { data } = history
  const empty = data.current.positions.length === 0 && tradeRows?.length === 0
  return (
    <div className="card-grid md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <Summary history={data} className="md:col-span-2" />
      {empty && <GetStarted className="md:col-span-2" />}
      <EquityPanel history={data} className="md:col-span-2 xl:col-span-1" />
      <AllocationPanel value={data.current} names={names} className="md:col-span-2 xl:col-span-1" />
      <Positions value={data.current} liveStockIds={data.live_stock_ids} names={names} className="md:col-span-2" />
      {!empty && (
        <TradesPanel trades={trades} rows={tradeRows} names={names} title={t('trades.title')} description={t('trades.question')} none={t('trades.none')} className="md:col-span-2" />
      )}
      <AsOfPanel />
      <AboutPanel />
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

/**
 * The account on a past day, asked on its own: while it loads the card says so and never shows another day's answer,
 * and a failure stays inside the card, under the account as it is now.
 */
function AsOfPanel() {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const [draft, setDraft] = useState('')
  const [asOf, setAsOf] = useState<string | null>(null)
  const lookup = useAccountHistory(asOf, asOf !== null)
  const busy = asOf !== null && lookup.isFetching
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setAsOf(/^\d{4}-\d{2}-\d{2}$/.test(draft) ? draft : null)
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
        ) : lookup.isPending ? (
          <Skeleton className="h-16 rounded-lg" />
        ) : lookup.isError ? (
          <ErrorState error={lookup.error} title={t('loadFailed')} onRetry={() => void lookup.refetch()} />
        ) : lookup.data.as_of ? (
          <div className="space-y-3">
            <p className="tabular text-xs text-muted-foreground">{t('asOfTitle', { time: formatDateTime(locale, lookup.data.as_of.last_fill_at) })}</p>
            <dl className="grid grid-cols-2 gap-4 @xl:grid-cols-4">
              <Stat label={t('value.equity')}>{formatNumber(locale, lookup.data.as_of.value.equity)}</Stat>
              <Stat label={t('value.cash')}>{formatNumber(locale, lookup.data.as_of.value.cash)}</Stat>
              <Stat label={t('value.marketValue')}>{formatNumber(locale, lookup.data.as_of.value.market_value)}</Stat>
              <Stat label={t('value.unrealized')}>
                <ChangeValue value={lookup.data.as_of.value.unrealized_pnl} format="absolute" fractionDigits={0} />
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

/** Which broker keeps the account, and that its money is not real, said once. */
function AboutPanel() {
  const { t } = useTranslation('account')
  return (
    <Panel title={t('about.title')}>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-6 gap-y-3 text-sm">
        <dt className="text-muted-foreground">{t('about.broker')}</dt>
        <dd>
          <Badge variant="outline" className="gap-1 border-gold/40 font-normal text-gold">
            <FlaskConical aria-hidden className="size-3" />
            {t('provider.mock')}
          </Badge>
        </dd>
      </dl>
      <p className="mt-4 border-t pt-4 text-sm text-pretty text-muted-foreground">{t('notice.mock')}</p>
    </Panel>
  )
}
