import { ReceiptText, Unplug, Wallet } from 'lucide-react'
import { useMemo, type ComponentType } from 'react'
import { useTranslation } from '@/i18n'
import { isApiError, useListedNames, type SaveConfirmationProps } from '@/shared/api'
import { DASH, useFormat } from '@/shared/lib/format'
import { ChangeValue } from '@/shared/ui/change-value'
import { StockLink } from '@/shared/ui/stock-name'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { ErrorState } from '@/shared/ui/error-state'
import { PageHeader } from '@/shared/ui/page-header'
import { Panel } from '@/shared/ui/panel'
import { AdministratorsOnly, RequireSignIn } from '@/shared/ui/require-sign-in'
import { PageSkeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { useBrokerageAccount, useTrades, type BrokerageStatement, type BrokerFill, type BrokerPosition, type Settlement } from './api'
import { loginState } from './model'
import { SinoPacPanel } from './SinoPacPanel'
import { TradesPanel } from './Trades'

/**
 * The SinoPac account: its server, its login and whether the site may order there lead, managed there by an
 * administrator through `Confirmation`, the settings save's confirmation the route hands in; then the account as the
 * broker reports it while the site's login is up, which the page only reads.
 */
export function BrokerageAccountPage({ Confirmation }: { Confirmation: ComponentType<SaveConfirmationProps> }) {
  const { t } = useTranslation('account')
  return (
    <div className="page-stack">
      <PageHeader title={t('page.shioaji.title')} />
      <RequireSignIn layout="page" needs="use_real_broker" reason={t('brokerage.signIn')}>
        <Brokerage Confirmation={Confirmation} />
      </RequireSignIn>
    </div>
  )
}

/**
 * A read SinoPac did not answer (broker_not_answering) fails the whole answer. Once an answer came, its server, login
 * and switches stay on the page through a later failed read, which then takes the statement's place with its retry.
 */
function Brokerage({ Confirmation }: { Confirmation: ComponentType<SaveConfirmationProps> }) {
  const { t } = useTranslation('account')
  const account = useBrokerageAccount()
  const retry = () => void account.refetch()
  if (account.isPending) return <PageSkeleton />
  if (account.isError && isApiError(account.error) && account.error.code === 'administrators_only') return <AdministratorsOnly layout="page" />
  if (account.isLoadingError) return <ErrorState error={account.error} title={t('brokerage.loadFailed')} onRetry={retry} framed />
  const { statement } = account.data
  const down = loginState(account.data) === 'down'
  return (
    <div className="card-stack">
      <SinoPacPanel account={account.data} Confirmation={Confirmation} />
      {account.isRefetchError ? (
        <ErrorState error={account.error} title={t('brokerage.loadFailed')} onRetry={retry} framed />
      ) : statement ? (
        <Statement statement={statement} />
      ) : (
        <StateBlock
          icon={Unplug}
          title={t(down ? 'brokerage.down.title' : 'brokerage.unavailable.title')}
          description={t(down ? 'brokerage.down.description' : 'brokerage.unavailable.description')}
          framed
        />
      )}
    </div>
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
      <FillsPanel title={t('brokerage.fills.title')} none={t('brokerage.fills.none')} fills={statement.fills} names={names} />
      <FillsPanel
        title={t('brokerage.sales.title')}
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
  const format = useFormat()
  return (
    <Panel className={className}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 @xl:grid-cols-4">
        <Stat size="lg" label={t(statement.simulation ? 'brokerage.summary.figuredCash' : 'brokerage.summary.balance')}>
          {format.number(statement.balance)}
        </Stat>
        <Stat size="lg" label={t('value.marketValue')}>
          {format.number(statement.market_value)}
        </Stat>
        <Stat size="lg" label={t('value.unrealized')}>
          <ChangeValue value={statement.unrealized_pnl} format="absolute" fractionDigits={0} />
        </Stat>
        <Stat size="lg" label={t('brokerage.summary.realized', { date: format.monthDay(statement.sales_from) })}>
          <ChangeValue value={statement.realized_pnl} format="absolute" fractionDigits={0} />
        </Stat>
      </dl>
      {statement.simulation && <p className="mt-4 text-sm text-pretty text-muted-foreground">{t('brokerage.summary.figuredNote')}</p>}
    </Panel>
  )
}

function PositionsPanel({ positions, names, className }: { positions: readonly BrokerPosition[]; names: ReadonlyMap<string, string>; className?: string }) {
  const { t } = useTranslation('account')
  const format = useFormat()
  const columns: Column<BrokerPosition>[] = [
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <StockLink stockId={row.stock_id} name={names.get(row.stock_id)}>
          <span className="tabular truncate text-xs text-muted-foreground md:hidden">
            {t('brokerage.positions.line', { shares: format.number(row.quantity), cost: format.price(row.average_cost), price: format.price(row.mark_price) })}
          </span>
        </StockLink>
      ),
    },
    { key: 'quantity', header: t('column.quantity'), numeric: true, from: 'md', cell: (row) => format.number(row.quantity) },
    { key: 'cost', header: t('column.averageCost'), numeric: true, from: 'md', cell: (row) => format.price(row.average_cost) },
    { key: 'price', header: t('brokerage.positions.price'), numeric: true, from: 'md', cell: (row) => format.price(row.mark_price) },
    { key: 'value', header: t('column.marketValue'), numeric: true, cell: (row) => format.number(row.market_value) },
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
    <Panel className={className} title={t('brokerage.positions.title')} flush>
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
  const format = useFormat()
  const columns: Column<Settlement>[] = [
    { key: 'day', header: t('brokerage.settlements.day'), className: 'tabular w-full whitespace-nowrap', cell: (row) => format.date(row.settles_on) },
    {
      key: 'amount',
      header: t('brokerage.settlements.amount'),
      numeric: true,
      cell: (row) => (
        <span className="flex flex-col items-end leading-tight sm:flex-row sm:items-baseline sm:justify-end sm:gap-2">
          <span className="font-medium">{format.signed(row.amount, 0)}</span>
          {row.amount !== 0 && <span className="text-xs text-muted-foreground">{t(row.amount < 0 ? 'brokerage.settlements.pay' : 'brokerage.settlements.receive')}</span>}
        </span>
      ),
    },
  ]
  return (
    <Panel className={className} title={t('brokerage.settlements.title')} flush>
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
  none: string
  fills: readonly BrokerFill[]
  names: ReadonlyMap<string, string>
  /** Past sales carry their day and the profit or loss the broker says each realized; today's deals carry neither. */
  past?: boolean
  className?: string
}

type FillRow = BrokerFill & { key: string }

function FillsPanel({ title, none, fills, names, past = false, className }: FillsPanelProps) {
  const { t } = useTranslation('account')
  const format = useFormat()
  // The broker gives a deal no id, so its place in the answer names its row.
  const rows = useMemo(() => fills.map((fill, index): FillRow => ({ ...fill, key: String(index) })), [fills])
  const side = (row: FillRow) => t(`runs:action.${row.action}`)
  const line = (row: FillRow) => {
    const said = { side: side(row), shares: format.number(row.quantity), price: format.price(row.price) }
    return past ? t('brokerage.fill.lineDated', { ...said, date: format.monthDay(row.filled_on) }) : t('brokerage.fill.line', said)
  }
  const columns: Column<FillRow>[] = [
    ...(past ? [{ key: 'day', header: t('brokerage.fill.day'), from: 'md', className: 'tabular whitespace-nowrap text-muted-foreground', cell: (row) => format.date(row.filled_on) } satisfies Column<FillRow>] : []),
    {
      key: 'stock',
      header: t('column.stock'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <StockLink stockId={row.stock_id} name={names.get(row.stock_id)}>
          <span className="tabular truncate text-xs text-muted-foreground md:hidden">{line(row)}</span>
        </StockLink>
      ),
    },
    { key: 'side', header: t('brokerage.fill.side'), from: 'md', className: 'whitespace-nowrap', cell: side },
    { key: 'shares', header: t('column.quantity'), numeric: true, from: 'md', cell: (row) => format.number(row.quantity) },
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
    <Panel className={className} title={title} flush>
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
  return <TradesPanel trades={trades} rows={rows} names={names} title={t('brokerage.orders.title')} none={t('brokerage.orders.none')} className={className} />
}
