import { ArrowRight, FlaskConical, Landmark, ReceiptText, Unplug, Wallet } from 'lucide-react'
import { useMemo, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { isApiError, useListedNames, useShows } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { formatDateTime, formatNumber, formatSigned, useFormat } from '@/shared/lib/format'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { AdministratorsOnly, RequireSignIn } from '@/shared/ui/require-sign-in'
import { PageSkeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { useBrokerageAccount, useTrades, type BrokerageAccount, type BrokerageStatement, type BrokerFill, type BrokerPosition, type Settlement } from './api'
import { TradesPanel } from './Trades'

const DASH = '—'

/**
 * The SinoPac account as the broker reports it. The page only reads: which server it shows and whether the site may
 * order there lead, then the account while the site's login is up.
 */
export function BrokerageAccountPage() {
  const { t } = useTranslation('account')
  return (
    <div className="page-stack">
      <PageHeader title={t('page.shioaji.title')} description={t('page.shioaji.description')} />
      <RequireSignIn layout="page" needs="use_real_broker" reason={t('brokerage.signIn')}>
        <Brokerage />
      </RequireSignIn>
    </div>
  )
}

function Brokerage() {
  const { t } = useTranslation('account')
  const account = useBrokerageAccount()
  if (account.isPending) return <PageSkeleton />
  if (account.isError) {
    if (isApiError(account.error) && account.error.code === 'administrators_only') return <AdministratorsOnly layout="page" />
    return <ErrorState error={account.error} title={t('brokerage.loadFailed')} onRetry={() => void account.refetch()} framed />
  }
  const { statement } = account.data
  return (
    <div className="card-stack">
      <ServerPanel account={account.data} />
      {statement ? (
        <Statement statement={statement} />
      ) : (
        <StateBlock icon={Unplug} title={t('brokerage.down.title')} description={t('brokerage.down.description')} framed />
      )}
    </div>
  )
}

/** Which server the figures come from and whether the site may order there, before any figure. */
function ServerPanel({ account }: { account: BrokerageAccount }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const analysed = useShows('holdings')
  const server = account.simulation ? 'simulation' : 'live'
  const Icon = account.simulation ? FlaskConical : Landmark
  return (
    <Panel>
      <div className="space-y-3">
        <p className="flex items-center gap-2 text-title font-semibold">
          <Icon aria-hidden className="size-4.5 shrink-0 text-gold" />
          {t(`brokerage.server.${server}`)}
        </p>
        <p className="text-sm text-pretty">{t(account.ordering ? 'brokerage.ordering.on' : 'brokerage.ordering.off')}</p>
        {account.statement && (
          <p className="flex flex-wrap items-center gap-x-3 text-xs text-pretty text-muted-foreground">
            {t('brokerage.own', { time: formatDateTime(locale, account.statement.read_at) })}
            {analysed && (
              <Link to={paths.holdings} className="inline-flex min-h-11 items-center gap-1 text-brand underline-offset-4 hover:underline md:min-h-0">
                {t('brokerage.analysis')}
                <ArrowRight aria-hidden className="size-3.5" />
              </Link>
            )}
          </p>
        )}
      </div>
    </Panel>
  )
}

/** The account in the order it is read: what it is worth, what it holds, what is due, today's deals, then the past. */
function Statement({ statement }: { statement: BrokerageStatement }) {
  const { t } = useTranslation('account')
  const format = useFormat()
  const codes = useMemo(() => [...new Set([...statement.positions, ...statement.fills, ...statement.sales].map((row) => row.stock_id))], [statement])
  const names = useListedNames(codes)
  const since = format.date(statement.sales_from)
  return (
    <div className="grid items-start gap-4 md:grid-cols-2 lg:gap-5">
      <SummaryPanel statement={statement} className="md:col-span-2" />
      <PositionsPanel positions={statement.positions} names={names} className="md:col-span-2" />
      <SettlementsPanel settlements={statement.settlements} />
      <FillsPanel title={t('brokerage.fills.title')} description={t('brokerage.fills.question')} none={t('brokerage.fills.none')} fills={statement.fills} names={names} />
      <FillsPanel
        title={t('brokerage.sales.title')}
        description={t('brokerage.sales.question', { date: since })}
        none={t('brokerage.sales.none', { date: since })}
        fills={statement.sales}
        names={names}
        past
        className="md:col-span-2"
      />
      <SiteOrders className="md:col-span-2" />
    </div>
  )
}

function SummaryPanel({ statement, className }: { statement: BrokerageStatement; className?: string }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const format = useFormat()
  return (
    <Panel className={className}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 @xl:grid-cols-4">
        <Stat size="lg" label={t('brokerage.summary.balance')}>
          {formatNumber(locale, statement.balance)}
        </Stat>
        <Stat size="lg" label={t('value.marketValue')}>
          {formatNumber(locale, statement.market_value)}
        </Stat>
        <Stat size="lg" label={t('value.unrealized')}>
          <ChangeValue value={statement.unrealized_pnl} format="absolute" fractionDigits={0} />
        </Stat>
        <Stat size="lg" label={t('brokerage.summary.realized', { date: format.monthDay(statement.sales_from) })}>
          <ChangeValue value={statement.realized_pnl} format="absolute" fractionDigits={0} />
        </Stat>
      </dl>
    </Panel>
  )
}

function StockLink({ stockId, names, children }: { stockId: string; names: ReadonlyMap<string, string>; children?: ReactNode }) {
  return (
    <Link to={paths.stock(stockId)} className="stretched-link flex min-w-0 flex-col justify-center hover:text-brand focus-visible:text-brand">
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="truncate font-medium" title={names.get(stockId)}>
          {names.get(stockId) ?? stockId}
        </span>
        <span className="shrink-0 font-mono text-xs text-muted-foreground">{stockId}</span>
      </span>
      {children}
    </Link>
  )
}

function PositionsPanel({ positions, names, className }: { positions: readonly BrokerPosition[]; names: ReadonlyMap<string, string>; className?: string }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const format = useFormat()
  const columns: Column<BrokerPosition>[] = [
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <StockLink stockId={row.stock_id} names={names}>
          <span className="tabular truncate text-xs text-muted-foreground md:hidden">
            {t('brokerage.positions.line', { shares: formatNumber(locale, row.quantity), cost: format.price(row.average_cost), price: format.price(row.mark_price) })}
          </span>
        </StockLink>
      ),
    },
    { key: 'quantity', header: t('column.quantity'), numeric: true, from: 'md', cell: (row) => formatNumber(locale, row.quantity) },
    { key: 'cost', header: t('column.averageCost'), numeric: true, from: 'md', cell: (row) => format.price(row.average_cost) },
    { key: 'price', header: t('brokerage.positions.price'), numeric: true, from: 'md', cell: (row) => format.price(row.mark_price) },
    { key: 'value', header: t('column.marketValue'), numeric: true, cell: (row) => formatNumber(locale, row.market_value) },
    {
      key: 'pnl',
      header: t('column.unrealized'),
      numeric: true,
      cell: (row) => (
        <span className="flex flex-col items-end leading-tight sm:flex-row sm:items-baseline sm:justify-end sm:gap-2">
          <ChangeValue value={row.unrealized_pnl} format="absolute" fractionDigits={0} />
          {row.unrealized_return !== null && <ChangeValue value={row.unrealized_return} format="percent" className="text-xs" />}
        </span>
      ),
    },
  ]
  return (
    <Panel className={className} title={t('brokerage.positions.title')} description={t('brokerage.positions.question', { count: positions.length })} flush>
      {positions.length === 0 ? (
        <StateBlock icon={Wallet} title={t('brokerage.positions.none')} />
      ) : (
        <DataTable rows={positions} columns={columns} rowKey={(row) => row.stock_id} label={t('brokerage.positions.title')} />
      )}
    </Panel>
  )
}

function SettlementsPanel({ settlements, className }: { settlements: readonly Settlement[]; className?: string }) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const format = useFormat()
  const columns: Column<Settlement>[] = [
    { key: 'day', header: t('brokerage.settlements.day'), className: 'tabular w-full whitespace-nowrap', cell: (row) => format.date(row.settles_on) },
    {
      key: 'amount',
      header: t('brokerage.settlements.amount'),
      numeric: true,
      cell: (row) => (
        <span className="flex flex-col items-end leading-tight sm:flex-row sm:items-baseline sm:justify-end sm:gap-2">
          <span className="font-medium">{formatSigned(locale, row.amount, 0)}</span>
          {row.amount !== 0 && <span className="text-xs text-muted-foreground">{t(row.amount < 0 ? 'brokerage.settlements.pay' : 'brokerage.settlements.receive')}</span>}
        </span>
      ),
    },
  ]
  return (
    <Panel className={className} title={t('brokerage.settlements.title')} description={t('brokerage.settlements.question')} flush>
      {settlements.length === 0 ? (
        <StateBlock icon={ReceiptText} title={t('brokerage.settlements.none')} />
      ) : (
        <DataTable rows={settlements} columns={columns} rowKey={(row) => row.settles_on} label={t('brokerage.settlements.title')} />
      )}
    </Panel>
  )
}

interface FillsPanelProps {
  title: string
  description: string
  none: string
  fills: readonly BrokerFill[]
  names: ReadonlyMap<string, string>
  /** Past sales carry their day and the profit or loss the broker says each realized; today's deals carry neither. */
  past?: boolean
  className?: string
}

type FillRow = BrokerFill & { key: string }

function FillsPanel({ title, description, none, fills, names, past = false, className }: FillsPanelProps) {
  const { t } = useTranslation('account')
  const locale = useLocale()
  const format = useFormat()
  // The broker gives a deal no id, so its place in the answer names its row.
  const rows = useMemo(() => fills.map((fill, index): FillRow => ({ ...fill, key: String(index) })), [fills])
  const side = (row: FillRow) => t(`runs:action.${row.action}`)
  const line = (row: FillRow) => {
    const said = { side: side(row), shares: formatNumber(locale, row.quantity), price: format.price(row.price) }
    return past ? t('brokerage.fill.lineDated', { ...said, date: format.monthDay(row.filled_on) }) : t('brokerage.fill.line', said)
  }
  const columns: Column<FillRow>[] = [
    ...(past ? [{ key: 'day', header: t('brokerage.fill.day'), from: 'md', className: 'tabular whitespace-nowrap text-muted-foreground', cell: (row) => format.date(row.filled_on) } satisfies Column<FillRow>] : []),
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <StockLink stockId={row.stock_id} names={names}>
          <span className="tabular truncate text-xs text-muted-foreground md:hidden">{line(row)}</span>
        </StockLink>
      ),
    },
    { key: 'side', header: t('brokerage.fill.side'), from: 'md', className: 'whitespace-nowrap', cell: side },
    { key: 'shares', header: t('column.quantity'), numeric: true, from: 'md', cell: (row) => formatNumber(locale, row.quantity) },
    { key: 'price', header: t('brokerage.fill.price'), numeric: true, from: 'md', cell: (row) => format.price(row.price) },
    ...(past
      ? [
          {
            key: 'realized',
            header: t('brokerage.fill.realized'),
            numeric: true,
            cell: (row) => (row.realized_pnl === null || row.realized_pnl === undefined ? DASH : <ChangeValue value={row.realized_pnl} format="absolute" fractionDigits={0} />),
          } satisfies Column<FillRow>,
        ]
      : []),
  ]
  return (
    <Panel className={className} title={title} description={description} flush>
      {rows.length === 0 ? <StateBlock icon={ReceiptText} title={none} /> : <DataTable rows={rows} columns={columns} rowKey={(row) => row.key} label={title} />}
    </Panel>
  )
}

/** The orders this site placed on SinoPac, from the site's own record: asked only while the login is up. */
function SiteOrders({ className }: { className?: string }) {
  const { t } = useTranslation('account')
  const trades = useTrades('shioaji')
  const rows = useMemo(() => trades.data?.pages.flatMap((page) => page.trades), [trades.data])
  const codes = useMemo(() => [...new Set((rows ?? []).map((trade) => trade.order.stock_id))], [rows])
  const names = useListedNames(codes)
  return <TradesPanel trades={trades} rows={rows} names={names} title={t('brokerage.orders.title')} description={t('brokerage.orders.question')} none={t('brokerage.orders.none')} className={className} />
}
