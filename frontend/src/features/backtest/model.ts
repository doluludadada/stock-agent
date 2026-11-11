import type { FieldProblem, Schemas } from '@/shared/api'
import { sessionDate } from '@/shared/lib/chart-range'
import { directionOf, type Direction } from '@/shared/lib/direction'

export type Backtest = Schemas['BacktestResponse']
export type BacktestSummary = Schemas['BacktestSummary']
export type BacktestInputs = Schemas['BacktestInputs']
type BacktestTrade = Schemas['BacktestTrade']

/** The answer to "would I have made money": the result in cash and percent, and against the TAIEX over the same sessions. */
export interface Verdict {
  outcome: Direction
  /** Final equity minus the starting cash. */
  profit: number
  ratio: number
  /** The TAIEX over the same sessions; null when the history holds no index bars for them. */
  benchmark: number | null
  /** The strategy's return minus the index's, with its side; null without the index. */
  lead: { side: 'ahead' | 'behind' | 'level'; points: number } | null
  /** False when the strategy bought nothing, which is a result of its own. */
  traded: boolean
}

export function verdictOf(backtest: BacktestSummary): Verdict {
  const profit = backtest.final_equity - backtest.inputs.initial_cash
  const benchmark = backtest.benchmark_return_pct
  const gap = benchmark === null ? null : backtest.total_return_pct - benchmark
  return {
    outcome: directionOf(profit),
    profit,
    ratio: backtest.total_return_pct,
    benchmark,
    lead: gap === null ? null : { side: gap > 0 ? 'ahead' : gap < 0 ? 'behind' : 'level', points: Math.abs(gap) },
    traded: backtest.trade_count > 0,
  }
}

/** The winning trades over all trades; null without a trade. */
export function winRate(backtest: BacktestSummary): number | null {
  return backtest.trade_count ? backtest.winning_trades / backtest.trade_count : null
}

/** One session of both curves as a return since the backtest began, so the account and the index share one axis. */
export interface ReturnPoint {
  date: string
  /** The account's equity over the starting cash, minus one. */
  strategy: number
  /** The TAIEX close over its close on the first session, minus one; null on a session the index has no bar for. */
  benchmark: number | null
}

/**
 * Both curves from the same start, oldest first. Their last points are the answer's `total_return_pct` and
 * `benchmark_return_pct`, because the bases are the same: the starting cash and the index's first bar.
 */
export function returnCurve(backtest: Pick<Backtest, 'equity_curve' | 'benchmark' | 'inputs'>): ReturnPoint[] {
  const base = backtest.benchmark[0]?.close
  const closes = new Map(backtest.benchmark.map((bar) => [sessionDate(bar.ts), bar.close]))
  return Object.entries(backtest.equity_curve)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, account]) => {
      const close = closes.get(date)
      return { date, strategy: account.equity / backtest.inputs.initial_cash - 1, benchmark: base && close !== undefined ? close / base - 1 : null }
    })
}

export type ExitReason = 'stopLoss' | 'score' | 'open' | 'other'

/** Only the stop-loss and the score sell in a backtest; the contract's other sources are a run's. */
const EXIT_REASON: Record<Schemas['SignalSource'], ExitReason> = { stop_loss: 'stopLoss', combined: 'score', manual: 'other', follow: 'other' }

export interface TradeRow {
  key: string
  stockId: string
  name: string | null
  quantity: number
  boughtOn: string
  /** Per share, the buy fees included. */
  averageCost: number
  /** Null while the position is still held at the last session. */
  sale: { on: string; at: number } | null
  pnl: number
  returnRatio: number
  heldSessions: number
  exit: ExitReason
}

export function tradeRows(trades: readonly BacktestTrade[]): TradeRow[] {
  return trades.map((trade, index) => ({
    key: `${index}-${trade.stock_id}-${trade.bought_on}`,
    stockId: trade.stock_id,
    name: trade.stock_name,
    quantity: trade.quantity,
    boughtOn: trade.bought_on,
    averageCost: trade.average_cost,
    sale: trade.sold_on !== null && trade.sold_at !== null ? { on: trade.sold_on, at: trade.sold_at } : null,
    pnl: trade.pnl,
    returnRatio: trade.return_pct,
    heldSessions: trade.held_sessions,
    exit: trade.exit_source === null ? 'open' : EXIT_REASON[trade.exit_source],
  }))
}

export type TradeSortKey = 'bought' | 'sold' | 'pnl' | 'return' | 'held'

export interface TradeSort {
  key: TradeSortKey
  descending: boolean
}

/** An open trade sorts as sold after every sale. */
const STILL_OPEN = '9999-12-31'

const SORT_VALUE: Record<TradeSortKey, (row: TradeRow) => number | string> = {
  bought: (row) => row.boughtOn,
  sold: (row) => row.sale?.on ?? STILL_OPEN,
  pnl: (row) => row.pnl,
  return: (row) => row.returnRatio,
  held: (row) => row.heldSessions,
}

export function sortTrades(rows: readonly TradeRow[], sort: TradeSort): TradeRow[] {
  const value = SORT_VALUE[sort.key]
  const order = (a: TradeRow, b: TradeRow) => {
    const [x, y] = [value(a), value(b)]
    return x < y ? -1 : x > y ? 1 : 0
  }
  return [...rows].sort((a, b) => (sort.descending ? order(b, a) : order(a, b)))
}

/** A second click on the sorted column turns it around; a new column starts with its largest or latest first. */
export function nextSort(current: TradeSort, key: TradeSortKey): TradeSort {
  return current.key === key ? { key, descending: !current.descending } : { key, descending: true }
}

/** The form as typed. */
export interface Draft {
  first: string
  last: string
  cash: string
  buy: string
  sell: string
}

export type DraftField = keyof Draft

export function draftOf(inputs: BacktestInputs): Draft {
  return { first: inputs.first, last: inputs.last, cash: String(inputs.initial_cash), buy: String(inputs.buy_score), sell: String(inputs.sell_score) }
}

/** The days a backtest may cover now: the period of the longest one the server allows. */
export interface Bounds {
  first: string
  last: string
}

export type DraftProblem = 'dateRequired' | 'beforeFirst' | 'afterLast' | 'firstAfterLast' | 'cash' | 'score'

export type ParsedDraft = { ok: true; inputs: BacktestInputs } | { ok: false; problems: Partial<Record<DraftField, DraftProblem>> }

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
export const SCORE_RANGE = { min: 0, max: 100 } as const

function dateProblem(date: string, bounds: Bounds): DraftProblem | null {
  if (!ISO_DATE.test(date)) return 'dateRequired'
  if (date < bounds.first) return 'beforeFirst'
  if (date > bounds.last) return 'afterLast'
  return null
}

function scoreProblem(text: string): DraftProblem | null {
  const score = Number(text)
  return text.trim() !== '' && Number.isInteger(score) && score >= SCORE_RANGE.min && score <= SCORE_RANGE.max ? null : 'score'
}

/** The typed form as the request's inputs, or what is wrong at each field, by the contract's own bounds. */
export function parseDraft(draft: Draft, bounds: Bounds): ParsedDraft {
  const cash = Number(draft.cash)
  const first = dateProblem(draft.first, bounds)
  const last = dateProblem(draft.last, bounds)
  const found: Record<DraftField, DraftProblem | null> = {
    first,
    last: last ?? (!first && draft.first > draft.last ? 'firstAfterLast' : null),
    cash: draft.cash.trim() !== '' && Number.isFinite(cash) && cash > 0 ? null : 'cash',
    buy: scoreProblem(draft.buy),
    sell: scoreProblem(draft.sell),
  }
  const problems = Object.fromEntries(Object.entries(found).filter(([, problem]) => problem !== null)) as Partial<Record<DraftField, DraftProblem>>
  if (Object.keys(problems).length > 0) return { ok: false, problems }
  return { ok: true, inputs: { first: draft.first, last: draft.last, initial_cash: cash, buy_score: Number(draft.buy), sell_score: Number(draft.sell) } }
}

const REQUEST_FIELD: Record<string, DraftField> = { first: 'first', last: 'last', initial_cash: 'cash', buy_score: 'buy', sell_score: 'sell' }

/** A 422's problems by the form field each names, in the server's words; a problem of no single field is left out. */
export function refusedFields(problems: readonly FieldProblem[]): Partial<Record<DraftField, string>> {
  const fields: Partial<Record<DraftField, string>> = {}
  for (const problem of problems) {
    const field = REQUEST_FIELD[String(problem.location.at(-1))]
    if (field) fields[field] ??= problem.message
  }
  return fields
}

export type PresetKey = '3M' | '6M' | '1Y' | 'all'

export interface PeriodPreset {
  key: PresetKey
  first: string
  last: string
}

const PRESET_MONTHS = { '3M': 3, '6M': 6, '1Y': 12 } as const

/** The same day `months` earlier, or that month's last day when it is shorter. */
export function monthsBefore(date: string, months: number): string {
  const [year, month, day] = date.split('-').map(Number) as [number, number, number]
  const target = new Date(Date.UTC(year, month - 1 - months, 1))
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate()
  target.setUTCDate(Math.min(day, lastDay))
  return target.toISOString().slice(0, 10)
}

/** The quick periods, each ending on the last day available; one the history is too short for is left out. */
export function periodPresets(bounds: Bounds): PeriodPreset[] {
  const recent = (Object.keys(PRESET_MONTHS) as (keyof typeof PRESET_MONTHS)[])
    .map((key) => ({ key, first: monthsBefore(bounds.last, PRESET_MONTHS[key]), last: bounds.last }))
    .filter((preset) => preset.first > bounds.first)
  return [...recent, { key: 'all', first: bounds.first, last: bounds.last }]
}

/** The buy score to try after a backtest that bought nothing: the built-in strategies' technical score rarely passes 75. */
export function lowerBuyScore(buyScore: number): number {
  return buyScore > 70 ? 70 : Math.max(buyScore - 10, SCORE_RANGE.min)
}
