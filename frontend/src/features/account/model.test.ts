import type { AccountHistory } from './api'
import { equityPoints, holdings, moveBetween, quotedAt, unrealizedRatio, withLatest, type AccountValue } from './model'

const position = (stock_id: string, quantity: number, average_cost: number, mark_price: number) => ({
  stock_id,
  quantity,
  average_cost,
  mark_price,
  marked_at: '2026-11-03T13:30:00+08:00',
  market_value: quantity * mark_price,
  unrealized_pnl: quantity * (mark_price - average_cost),
  cost_basis: quantity * average_cost,
  unrealized_return: mark_price / average_cost - 1,
  opened_at: null,
  weight: (quantity * mark_price) / 500_000,
})

const value: AccountValue = {
  cash: 100_000,
  market_value: 400_000,
  unrealized_pnl: 0,
  equity: 500_000,
  positions: [position('2317', 1000, 250, 240), position('2330', 100, 2000, 2200)],
}
value.unrealized_pnl = value.positions.reduce((sum, item) => sum + item.unrealized_pnl, 0)

describe('the account blotter', () => {
  it('lists the largest position first, as the server valued it', () => {
    expect(holdings(value)).toEqual([value.positions[0], value.positions[1]])
    expect(holdings({ ...value, positions: [value.positions[1]!, value.positions[0]!] }).map((row) => row.stock_id)).toEqual(['2317', '2330'])
  })

  it('measures the unrealized result against what the positions cost', () => {
    expect(unrealizedRatio(value)).toBeCloseTo(10_000 / 450_000)
    expect(unrealizedRatio({ ...value, positions: [], unrealized_pnl: 0 })).toBe(0)
  })

  it('orders the daily equity by date and measures a move between two days', () => {
    const day = (equity: number): AccountValue => ({ ...value, equity })
    const history = { equity_curve: { '2026-11-03': day(990_000), '2026-10-31': day(1_000_000) } } as unknown as AccountHistory
    const points = equityPoints(history)

    expect(points.map((point) => point.date)).toEqual(['2026-10-31', '2026-11-03'])
    expect(moveBetween(points[0], points[1])).toEqual({ change: -10_000, ratio: -0.01 })
    expect(moveBetween(undefined, points[1])).toBeNull()
  })
})

describe('the account at today’s quotes', () => {
  const history: AccountHistory = {
    current: value,
    equity_curve: { '2026-11-02': { ...value, equity: 480_000 }, '2026-11-03': value },
    as_of: null,
    opening: { initial_cash: 450_000, opened_at: '2026-10-30T09:00:00+08:00' },
    profit: 50_000,
    execution_provider: 'mock',
    live_stock_ids: [],
  }

  it('keeps the whole history until the server answers the account at today’s quotes, then shows that answer’s account and days over it', () => {
    expect(withLatest(history, undefined)).toBe(history)
    const today = { ...value, equity: 510_000 }
    const latest: AccountHistory = { ...history, current: today, live_stock_ids: ['2330'], profit: 60_000, equity_curve: { '2026-11-04': today } }
    const shown = withLatest(history, latest)
    expect(shown).toMatchObject({ current: today, live_stock_ids: ['2330'], profit: 60_000, opening: history.opening })
    const points = equityPoints(shown)
    expect(points.map((point) => point.date)).toEqual(['2026-11-02', '2026-11-03', '2026-11-04'])
    expect(moveBetween(points.at(-2), points.at(-1))).toEqual({ change: 10_000, ratio: 0.02 })
  })

  it('says no time while the server priced no position at today’s quote', () => {
    expect(quotedAt(history)).toBeNull()
  })

  it('says the newest trade among the positions the server priced at today’s quote', () => {
    const [settled, live] = value.positions
    const quoted = { ...history, live_stock_ids: ['2330'], current: { ...value, positions: [settled!, { ...live!, marked_at: '2026-11-04T10:32:00+08:00' }] } }
    expect(quotedAt(quoted)).toBe('2026-11-04T10:32:00+08:00')
  })
})
