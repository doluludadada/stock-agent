import type { AccountHistory } from './api'
import { equityPoints, holdings, moveBetween, unrealizedRatio, type AccountValue } from './model'

const position = (stock_id: string, quantity: number, average_cost: number, mark_price: number) => ({
  stock_id,
  quantity,
  average_cost,
  mark_price,
  marked_at: '2026-11-03T13:30:00+08:00',
  market_value: quantity * mark_price,
  unrealized_pnl: quantity * (mark_price - average_cost),
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
  it('lists the largest position first with its return and weight', () => {
    const rows = holdings(value)

    expect(rows.map((row) => row.stock_id)).toEqual(['2317', '2330'])
    expect(rows[0]).toMatchObject({ cost: 250_000, returnRatio: -0.04, weight: 0.48 })
    expect(rows[1]).toMatchObject({ cost: 200_000, returnRatio: 0.1, weight: 0.44 })
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
