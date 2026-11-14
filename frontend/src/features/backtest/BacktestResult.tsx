import { ArrowDown, ArrowUp, ArrowUpDown, Info, ReceiptText, SearchX } from 'lucide-react'
import { lazy, Suspense, useId, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { useLocale, useTranslation } from '@/i18n'
import { paths } from '@/shared/config/paths'
import { PRICE_TONE } from '@/shared/lib/direction'
import { formatDateTime, formatNumber, formatSignedPercent, useFormat } from '@/shared/lib/format'
import { cn } from '@/shared/lib/utils'
import { Badge } from '@/shared/ui/badge'
import { Button } from '@/shared/ui/button'
import { ChangeValue } from '@/shared/ui/change-value'
import { DataTable, type Column } from '@/shared/ui/data-table'
import { NotAdviceNote } from '@/shared/ui/not-advice-note'
import { Panel } from '@/shared/ui/panel'
import { ShowMore } from '@/shared/ui/show-more'
import { Skeleton } from '@/shared/ui/skeleton'
import { Stat } from '@/shared/ui/stat'
import { StateBlock } from '@/shared/ui/state-block'
import { lowerBuyScore, nextSort, returnCurve, sortTrades, tradeRows, verdictOf, winRate, type Backtest, type TradeRow, type TradeSort, type TradeSortKey, type Verdict } from './model'

const ComparisonChart = lazy(() => import('@/shared/ui/comparison-chart').then((module) => ({ default: module.ComparisonChart })))

const TRADES_SHOWN = 20

interface BacktestResultProps {
  backtest: Backtest
  /** Fills the form with this backtest's inputs, to run a variation of it. */
  onReuse: () => void
  /** Puts a lower buy score in the form after a backtest that bought nothing. */
  onTryBuyScore: (score: number) => void
}

/** One backtest, answer first: the verdict and its figures, both curves on one chart, how to read it, then every trade. */
export function BacktestResult({ backtest, onReuse, onTryBuyScore }: BacktestResultProps) {
  return (
    <div className="card-stack">
      <VerdictPanel backtest={backtest} onReuse={onReuse} onTryBuyScore={onTryBuyScore} />
      <CurvePanel backtest={backtest} />
      <ReadingNotes />
      <TradesPanel backtest={backtest} />
    </div>
  )
}

/** The verdict in one or two sentences; the same words lead the page and name a saved backtest for screen readers. */
function useVerdictText(backtest: Backtest, verdict: Verdict) {
  const { t } = useTranslation('backtest')
  const locale = useLocale()
  const format = useFormat()
  const period = t('period', { first: format.date(backtest.first_session), last: format.date(backtest.last_session) })
  const ratio = formatSignedPercent(locale, verdict.ratio)
  const result = verdict.traded
    ? t(`verdict.result.${verdict.outcome}`, { period, amount: formatNumber(locale, Math.abs(verdict.profit)), ratio })
    : t('verdict.noTrades', { period, cash: formatNumber(locale, backtest.final_equity) })
  const index =
    verdict.benchmark === null || verdict.lead === null
      ? t('verdict.index.none')
      : t(`verdict.index.${verdict.lead.side}`, { benchmark: formatSignedPercent(locale, verdict.benchmark), points: formatNumber(locale, verdict.lead.points * 100, 1) })
  return { result, index }
}

function VerdictPanel({ backtest, onReuse, onTryBuyScore }: BacktestResultProps) {
  const { t } = useTranslation('backtest')
  const locale = useLocale()
  const verdict = useMemo(() => verdictOf(backtest), [backtest])
  const text = useVerdictText(backtest, verdict)
  const wins = winRate(backtest)
  const sessions = Object.keys(backtest.equity_curve).length
  const { inputs } = backtest
  return (
    <Panel
      title={t('result.title')}
      description={t('result.ran', { strategy: backtest.strategy_name, sessions, time: formatDateTime(locale, backtest.created_at) })}
      aside={
        <Button type="button" variant="outline" size="sm" onClick={onReuse}>
          {t('result.reuse')}
        </Button>
      }
    >
      <div className="space-y-5">
        <div className="space-y-2">
          <p className={cn('figure', PRICE_TONE[verdict.outcome])}>{formatSignedPercent(locale, verdict.ratio)}</p>
          <p className="max-w-3xl text-title font-medium text-pretty" data-testid="verdict">
            {text.result} <span className="font-normal text-muted-foreground">{text.index}</span>
          </p>
        </div>
        {!verdict.traded && <NoTrades buyScore={inputs.buy_score} onTryBuyScore={onTryBuyScore} />}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-t pt-4 @xl:grid-cols-4">
          <Stat size="lg" label={t('stat.finalEquity')}>
            {formatNumber(locale, backtest.final_equity)}
            <span className="block text-xs font-normal text-muted-foreground">{t('stat.from', { cash: formatNumber(locale, inputs.initial_cash) })}</span>
          </Stat>
          <Stat size="lg" label={t('stat.totalReturn')}>
            <ChangeValue value={backtest.total_return_pct} format="percent" />
            <span className="block text-xs font-normal">
              <ChangeValue value={verdict.profit} format="absolute" fractionDigits={0} />
            </span>
          </Stat>
          <Stat size="lg" label={t('stat.benchmark')}>
            {backtest.benchmark_return_pct === null ? '—' : <ChangeValue value={backtest.benchmark_return_pct} format="percent" />}
            <span className="block text-xs font-normal text-muted-foreground">{t('stat.sameSessions')}</span>
          </Stat>
          <Stat size="lg" label={t('stat.maxDrawdown')}>
            {formatSignedPercent(locale, -backtest.max_drawdown_pct)}
            <span className="block text-xs font-normal text-muted-foreground">{t('stat.fromHigh')}</span>
          </Stat>
          <Stat size="lg" label={t('stat.trades')}>
            {formatNumber(locale, backtest.trade_count)}
            {wins !== null && (
              <span className="block text-xs font-normal text-muted-foreground">
                {t('stat.wins', { wins: backtest.winning_trades, rate: formatNumber(locale, wins * 100, 0) })}
              </span>
            )}
          </Stat>
          <Stat size="lg" label={t('stat.averageHeld')}>
            {backtest.average_held_sessions === null ? '—' : t('sessions', { value: formatNumber(locale, backtest.average_held_sessions, 1) })}
          </Stat>
          <Stat size="lg" label={t('stat.costs')}>
            {formatNumber(locale, backtest.fee + backtest.tax)}
            <span className="block text-xs font-normal text-muted-foreground">
              {t('stat.feeAndTax', { fee: formatNumber(locale, backtest.fee), tax: formatNumber(locale, backtest.tax) })}
            </span>
          </Stat>
          <Stat size="lg" label={t('stat.scores')}>
            {t('stat.buySell', { buy: inputs.buy_score, sell: inputs.sell_score })}
            <span className="block text-xs font-normal text-muted-foreground">
              {t('stat.rules', { stopLoss: formatNumber(locale, backtest.stop_loss_pct * 100, 1), risk: formatNumber(locale, backtest.risk_per_trade_pct * 100, 1) })}
            </span>
          </Stat>
        </dl>
      </div>
    </Panel>
  )
}

/** A backtest that bought nothing is a result: it says why that is likely and what to try. */
function NoTrades({ buyScore, onTryBuyScore }: { buyScore: number; onTryBuyScore: (score: number) => void }) {
  const { t } = useTranslation('backtest')
  const lower = lowerBuyScore(buyScore)
  return (
    <div role="note" className="flex flex-wrap items-start gap-3 rounded-lg border border-gold/40 bg-gold-soft px-3 py-2.5 text-sm">
      <SearchX aria-hidden className="mt-0.5 size-4 shrink-0 text-gold" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium">{t('noTrades.title')}</p>
        <p className="text-pretty text-muted-foreground">{t('noTrades.why', { score: buyScore })}</p>
      </div>
      {lower < buyScore && (
        <Button type="button" variant="outline" size="sm" onClick={() => onTryBuyScore(lower)}>
          {t('noTrades.try', { score: lower })}
        </Button>
      )}
    </div>
  )
}

function CurvePanel({ backtest }: { backtest: Backtest }) {
  const { t } = useTranslation('backtest')
  const locale = useLocale()
  const format = useFormat()
  const points = useMemo(() => returnCurve(backtest).map((point) => ({ date: point.date, value: point.strategy, benchmark: point.benchmark })), [backtest])
  return (
    <Panel title={t('curve.title')} description={t('curve.question')} aside={<span className="tabular">{t('period', { first: format.date(backtest.first_session), last: format.date(backtest.last_session) })}</span>}>
      <Suspense fallback={<Skeleton className="h-(--chart-price-height) rounded-xl" />}>
        <ComparisonChart
          data={points}
          valueLabel={t('curve.strategy')}
          benchmarkLabel={t('curve.benchmark')}
          baseline={0}
          formatValue={(ratio) => formatSignedPercent(locale, ratio)}
          formatAxisValue={(ratio) => formatSignedPercent(locale, ratio, 0)}
          formatAxisDate={format.monthDay}
          formatTooltipDate={(date) => format.date(date, 'long')}
        />
      </Suspense>
    </Panel>
  )
}

const READING_NOTES = ['technicalOnly', 'nextOpen', 'listedToday'] as const

/** What a backtest leaves out, said beside every result and before the first one. */
export function ReadingNotes({ className }: { className?: string }) {
  const { t } = useTranslation('backtest')
  return (
    <Panel className={className} title={t('notes.title')}>
      <ul className="space-y-2 text-sm text-pretty text-muted-foreground">
        {READING_NOTES.map((note) => (
          <li key={note} className="flex items-start gap-2">
            <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-gold" />
            {t(`notes.${note}`)}
          </li>
        ))}
      </ul>
      <NotAdviceNote className="mt-3 border-t pt-3" />
    </Panel>
  )
}

const EXIT_TONE: Record<TradeRow['exit'], string> = {
  stopLoss: 'border-destructive/40 text-destructive',
  score: '',
  open: 'border-primary/40 text-primary',
  other: '',
}

function TradesPanel({ backtest }: { backtest: Backtest }) {
  const { t } = useTranslation('backtest')
  const locale = useLocale()
  const format = useFormat()
  const tableId = useId()
  const [sort, setSort] = useState<TradeSort>({ key: 'bought', descending: false })
  const [expanded, setExpanded] = useState(false)
  const rows = useMemo(() => sortTrades(tradeRows(backtest.trades), sort), [backtest.trades, sort])
  const shown = expanded ? rows : rows.slice(0, TRADES_SHOWN)

  const sortable = (key: TradeSortKey) => {
    const active = sort.key === key
    const Icon = !active ? ArrowUpDown : sort.descending ? ArrowDown : ArrowUp
    const column = t(`trades.column.${key}`)
    return (
      <button
        type="button"
        onClick={() => setSort(nextSort(sort, key))}
        aria-label={t('trades.sortBy', { column })}
        aria-pressed={active}
        className={cn('inline-flex min-h-9 items-center gap-1 rounded-sm outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring', active && 'text-foreground')}
      >
        {column}
        <Icon aria-hidden className={cn('size-3', !active && 'opacity-50')} />
      </button>
    )
  }
  const day = (date: string, price: number) => (
    <>
      {format.date(date)}
      <span className="block text-xs text-muted-foreground">{format.price(price)}</span>
    </>
  )
  const sold = (row: TradeRow) => (row.sale ? t('trades.soldLine', { date: format.monthDay(row.sale.on), price: format.price(row.sale.at) }) : t('exit.open'))

  const columns: Column<TradeRow>[] = [
    {
      key: 'stock',
      header: t('trades.column.stock'),
      className: 'w-full max-w-0',
      cell: (row) => (
        <Link to={paths.stock(row.stockId)} className="flex min-h-11 min-w-0 flex-col justify-center hover:text-brand focus-visible:text-brand md:min-h-0">
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="truncate font-medium">{row.name ?? row.stockId}</span>
            {row.name !== null && <span className="shrink-0 font-mono text-xs text-muted-foreground">{row.stockId}</span>}
          </span>
          <span className="tabular truncate text-xs text-muted-foreground lg:hidden">
            {t('trades.line', { bought: format.monthDay(row.boughtOn), cost: format.price(row.averageCost), sold: sold(row) })}
          </span>
        </Link>
      ),
    },
    { key: 'bought', header: sortable('bought'), numeric: true, from: 'lg', cell: (row) => day(row.boughtOn, row.averageCost) },
    { key: 'sold', header: sortable('sold'), numeric: true, from: 'lg', cell: (row) => (row.sale ? day(row.sale.on, row.sale.at) : <span className="text-muted-foreground">{t('exit.open')}</span>) },
    { key: 'quantity', header: t('trades.column.quantity'), numeric: true, from: 'xl', cell: (row) => formatNumber(locale, row.quantity) },
    { key: 'pnl', header: sortable('pnl'), numeric: true, cell: (row) => <ChangeValue value={row.pnl} format="absolute" fractionDigits={0} /> },
    { key: 'return', header: sortable('return'), numeric: true, from: 'sm', cell: (row) => <ChangeValue value={row.returnRatio} format="percent" /> },
    { key: 'held', header: sortable('held'), numeric: true, from: 'md', cell: (row) => formatNumber(locale, row.heldSessions) },
    {
      key: 'exit',
      header: t('trades.column.exit'),
      from: 'md',
      cell: (row) => (
        <Badge variant="outline" className={cn('font-normal', EXIT_TONE[row.exit])}>
          {t(`exit.${row.exit}`)}
        </Badge>
      ),
    },
  ]

  return (
    <Panel
      flush
      title={t('trades.title')}
      description={t('trades.question')}
      aside={rows.length > 0 && <span className="tabular">{t('trades.count', { count: rows.length })}</span>}
      footer={
        rows.length > TRADES_SHOWN && (
          <ShowMore expanded={expanded} onToggle={() => setExpanded(!expanded)} controls={tableId} moreLabel={t('trades.more', { count: rows.length })} lessLabel={t('trades.less')} />
        )
      }
    >
      {rows.length === 0 ? <StateBlock icon={ReceiptText} title={t('trades.none')} /> : <DataTable id={tableId} rows={shown} columns={columns} rowKey={(row) => row.key} label={t('trades.title')} />}
    </Panel>
  )
}
