import { describe, expect, it } from 'vitest'
import openapi from '@/shared/api/openapi.json'
import {
  draftOf,
  lowerBuyScore,
  nextSort,
  parseDraft,
  periodPresets,
  refusedFields,
  returnCurve,
  SCORE_RANGE,
  sortTrades,
  tradeRows,
  verdictOf,
  winRate,
  type Backtest,
  type BacktestSummary,
} from './model'

const INPUTS = { first: '2026-05-04', last: '2026-11-11', initial_cash: 1_000_000, buy_score: 60, sell_score: 40 }
const BOUNDS = { first: '2025-11-12', last: '2026-11-11' }

const SUMMARY: BacktestSummary = {
  backtest_id: '11111111-1111-4111-8111-111111111111',
  created_at: '2026-11-12T02:00:00Z',
  strategy_id: 'trend',
  strategy_name: 'Trend',
  inputs: INPUTS,
  stop_loss_pct: 0.08,
  risk_per_trade_pct: 0.02,
  first_session: '2026-05-04',
  last_session: '2026-11-11',
  final_equity: 1_032_000,
  total_return_pct: 0.032,
  benchmark_return_pct: 0.446,
  max_drawdown_pct: 0.051,
  trade_count: 4,
  winning_trades: 3,
  fee: 1_200,
  tax: 900,
  average_held_sessions: 6.5,
}

const account = (equity: number) => ({ cash: equity, market_value: 0, unrealized_pnl: 0, equity, positions: [] })
const bar = (day: string, close: number) => ({ ts: `${day}T05:30:00Z`, open: close, high: close, low: close, close, volume: 0, change: null })

type Trade = Backtest['trades'][number]
const trade = (overrides: Partial<Trade>): Trade => ({
  stock_id: '2330',
  stock_name: '台積電',
  quantity: 1000,
  bought_on: '2026-05-05',
  average_cost: 100,
  sold_on: '2026-05-12',
  sold_at: 110,
  exit_source: 'combined',
  pnl: 9_000,
  fee: 300,
  tax: 330,
  held_sessions: 5,
  return_pct: 0.09,
  ...overrides,
})

describe('the verdict', () => {
  it('says a gain in cash and percent, and how far behind the index it ended', () => {
    const verdict = verdictOf(SUMMARY)
    expect(verdict).toMatchObject({ outcome: 'up', profit: 32_000, ratio: 0.032, benchmark: 0.446, traded: true })
    expect(verdict.lead?.side).toBe('behind')
    expect(verdict.lead?.points).toBeCloseTo(0.414)
  })

  it('says a loss that still beat a falling index is ahead', () => {
    const verdict = verdictOf({ ...SUMMARY, final_equity: 980_000, total_return_pct: -0.02, benchmark_return_pct: -0.1 })
    expect(verdict.outcome).toBe('down')
    expect(verdict.profit).toBe(-20_000)
    expect(verdict.lead?.side).toBe('ahead')
    expect(verdict.lead?.points).toBeCloseTo(0.08)
  })

  it('keeps a backtest without a trade as a result of its own, and one without index bars uncompared', () => {
    const verdict = verdictOf({ ...SUMMARY, final_equity: 1_000_000, total_return_pct: 0, benchmark_return_pct: null, trade_count: 0, winning_trades: 0 })
    expect(verdict).toEqual({ outcome: 'flat', profit: 0, ratio: 0, benchmark: null, lead: null, traded: false })
  })

  it('gives the win rate over all trades, and none without a trade', () => {
    expect(winRate(SUMMARY)).toBe(0.75)
    expect(winRate({ ...SUMMARY, trade_count: 0, winning_trades: 0 })).toBeNull()
  })
})

describe('the two curves', () => {
  const curve = returnCurve({
    inputs: INPUTS,
    // The server answers the days in session order; the curve must not depend on the object's key order.
    equity_curve: { '2026-05-06': account(1_032_000), '2026-05-04': account(1_000_000), '2026-05-05': account(990_000) },
    benchmark: [bar('2026-05-04', 20_000), bar('2026-05-05', 21_000), bar('2026-05-06', 28_920)],
  })

  it('start both at zero on the first session and end at the returns the summary reports', () => {
    expect(curve.map((point) => point.date)).toEqual(['2026-05-04', '2026-05-05', '2026-05-06'])
    expect(curve[0]).toEqual({ date: '2026-05-04', strategy: 0, benchmark: 0 })
    expect(curve[1]!.strategy).toBeCloseTo(-0.01)
    expect(curve[1]!.benchmark).toBeCloseTo(0.05)
    expect(curve[2]!.strategy).toBeCloseTo(0.032)
    expect(curve[2]!.benchmark).toBeCloseTo(0.446)
  })

  it('reads a bar stamped at the Taipei close as that session, and leaves a session without a bar empty', () => {
    const gapped = returnCurve({
      inputs: INPUTS,
      equity_curve: { '2026-05-04': account(1_000_000), '2026-05-05': account(1_000_000), '2026-05-06': account(1_000_000) },
      benchmark: [bar('2026-05-04', 20_000), { ...bar('2026-05-06', 22_000), ts: '2026-05-06T13:30:00+08:00' }],
    })
    expect(gapped.map((point) => point.benchmark)).toEqual([0, null, expect.closeTo(0.1)])
  })

  it('draw the strategy alone when the history holds no index bars', () => {
    const alone = returnCurve({ inputs: INPUTS, equity_curve: { '2026-05-04': account(1_010_000) }, benchmark: [] })
    expect(alone).toEqual([{ date: '2026-05-04', strategy: expect.closeTo(0.01), benchmark: null }])
  })
})

describe('the trade rows', () => {
  const rows = tradeRows([
    trade({}),
    trade({ stock_id: '2317', stock_name: null, bought_on: '2026-05-08', sold_on: '2026-05-11', sold_at: 92, exit_source: 'stop_loss', pnl: -8_500, return_pct: -0.085, held_sessions: 1 }),
    trade({ stock_id: '2454', bought_on: '2026-05-07', sold_on: null, sold_at: null, exit_source: null, pnl: 1_000, return_pct: 0.01, held_sessions: 30 }),
  ])

  it('say why each closed: the score, the stop-loss, or still open with no sale', () => {
    expect(rows.map((row) => [row.stockId, row.exit, row.sale])).toEqual([
      ['2330', 'score', { on: '2026-05-12', at: 110 }],
      ['2317', 'stopLoss', { on: '2026-05-11', at: 92 }],
      ['2454', 'open', null],
    ])
  })

  it('names a reason for every sell source of the contract', () => {
    for (const source of openapi.components.schemas.SignalSource.enum as Trade['exit_source'][]) {
      expect(tradeRows([trade({ exit_source: source })])[0]!.exit, String(source)).toMatch(/^(score|stopLoss|other)$/)
    }
  })

  it('sort by P&L, by return, by the buy date and by sessions held, either way', () => {
    const ids = (key: Parameters<typeof nextSort>[1], descending: boolean) => sortTrades(rows, { key, descending }).map((row) => row.stockId)
    expect(ids('pnl', true)).toEqual(['2330', '2454', '2317'])
    expect(ids('pnl', false)).toEqual(['2317', '2454', '2330'])
    expect(ids('return', true)).toEqual(['2330', '2454', '2317'])
    expect(ids('bought', false)).toEqual(['2330', '2454', '2317'])
    expect(ids('held', true)).toEqual(['2454', '2330', '2317'])
  })

  it('sort an open trade as sold after every sale', () => {
    expect(sortTrades(rows, { key: 'sold', descending: false }).map((row) => row.stockId)).toEqual(['2317', '2330', '2454'])
  })

  it('turn the sorted column around on a second click and start a new column with its largest first', () => {
    expect(nextSort({ key: 'pnl', descending: true }, 'pnl')).toEqual({ key: 'pnl', descending: false })
    expect(nextSort({ key: 'pnl', descending: false }, 'held')).toEqual({ key: 'held', descending: true })
  })
})

describe('the form', () => {
  it('starts from the options and parses back to the same inputs', () => {
    expect(draftOf(INPUTS)).toEqual({ first: '2026-05-04', last: '2026-11-11', cash: '1000000', buy: '60', sell: '40' })
    expect(parseDraft(draftOf(INPUTS), BOUNDS)).toEqual({ ok: true, inputs: INPUTS })
  })

  it('holds each field to the days available and the bounds of the contract', () => {
    const problems = (overrides: Partial<ReturnType<typeof draftOf>>) => {
      const parsed = parseDraft({ ...draftOf(INPUTS), ...overrides }, BOUNDS)
      return parsed.ok ? {} : parsed.problems
    }
    expect(problems({ first: '' })).toEqual({ first: 'dateRequired' })
    expect(problems({ first: '2025-11-11' })).toEqual({ first: 'beforeFirst' })
    expect(problems({ last: '2026-11-12' })).toEqual({ last: 'afterLast' })
    expect(problems({ first: '2026-06-02', last: '2026-06-01' })).toEqual({ last: 'firstAfterLast' })
    expect(problems({ cash: '0' })).toEqual({ cash: 'cash' })
    expect(problems({ cash: '' })).toEqual({ cash: 'cash' })
    expect(problems({ buy: '100.5', sell: '-1' })).toEqual({ buy: 'score', sell: 'score' })
    expect(problems({ buy: '101' })).toEqual({ buy: 'score' })
    expect(problems({ buy: '100', sell: '0' })).toEqual({})
  })

  it('takes one day as a period', () => {
    expect(parseDraft({ ...draftOf(INPUTS), first: '2026-06-01', last: '2026-06-01' }, BOUNDS).ok).toBe(true)
  })

  it('uses the score bounds of the contract', () => {
    const score = openapi.components.schemas.Score_int_
    expect(SCORE_RANGE).toEqual({ min: score.minimum, max: score.maximum })
  })

  it('names the form fields a refusal is about, and leaves out a problem of no field', () => {
    expect(
      refusedFields([
        { location: ['body', 'inputs', 'buy_score'], message: 'Input should be less than or equal to 100' },
        { location: ['body', 'inputs', 'initial_cash'], message: 'Input should be greater than 0' },
        { location: ['body', 'inputs'], message: 'first must not be after last' },
      ]),
    ).toEqual(['buy', 'cash'])
  })
})

describe('the quick periods', () => {
  it('end on the last day available and start the months before it', () => {
    expect(periodPresets(BOUNDS)).toEqual([
      { key: '3M', first: '2026-08-11', last: '2026-11-11' },
      { key: '6M', first: '2026-05-11', last: '2026-11-11' },
      { key: 'all', first: '2025-11-12', last: '2026-11-11' },
    ])
  })

  it('leave out a period the history is too short for', () => {
    expect(periodPresets({ first: '2026-09-01', last: '2026-11-11' }).map((preset) => preset.key)).toEqual(['all'])
    expect(periodPresets({ first: '2024-01-02', last: '2026-11-11' }).map((preset) => preset.key)).toEqual(['3M', '6M', '1Y', 'all'])
  })
})

describe('after a backtest that bought nothing', () => {
  it('suggests 70 for a higher buy score, then ten lower each time, never under the lowest score', () => {
    expect(lowerBuyScore(80)).toBe(70)
    expect(lowerBuyScore(70)).toBe(60)
    expect(lowerBuyScore(95)).toBe(85)
    expect(lowerBuyScore(5)).toBe(0)
    expect(lowerBuyScore(0)).toBe(0)
  })
})
