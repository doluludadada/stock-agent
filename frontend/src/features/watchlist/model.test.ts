import type { Loadable, StockQuote } from '@/shared/api'
import { byStock, daySummary, shownRows } from './model'

const entry = (stockId: string, type: 'manual' | 'technical' = 'manual', created = '2026-11-01T00:00:00Z') => ({
  stock_id: stockId,
  name: `name ${stockId}`,
  watchlist_type: type,
  created_at: created,
  expires_at: null,
})
const ready = (changeRatio: number, session = '2026-11-03'): Loadable<StockQuote> => ({ status: 'ready', value: { close: 100, changeRatio, session } })

describe('the watchlist’s session summary', () => {
  it('counts only the stocks that closed in the latest session and says how many closed earlier', () => {
    const rows = byStock([entry('2330'), entry('2317'), entry('0050'), entry('2603')])
    const quotes = new Map([
      ['2330', ready(-0.015)],
      ['2317', ready(0.02)],
      ['0050', ready(-0.08, '2026-11-02')],
      ['2603', { status: 'loading' } as const],
    ])

    const summary = daySummary(rows, quotes)

    expect(summary).toMatchObject({ session: '2026-11-03', up: 1, down: 1, flat: 0, earlier: 1 })
    expect(summary.average).toBeCloseTo(0.0025)
    expect(summary.best?.row.stockId).toBe('2317')
    expect(summary.worst?.row.stockId).toBe('2330')
  })

  it('names no best stock on a day when every stock fell', () => {
    const rows = byStock([entry('2330'), entry('2317')])
    const summary = daySummary(rows, new Map([['2330', ready(-0.01)], ['2317', ready(-0.03)]]))
    expect(summary.best).toBeNull()
    expect(summary.worst?.row.stockId).toBe('2317')
  })
})

describe('the watchlist’s rows', () => {
  it('filter by source and search, and sort by change with unquoted stocks last', () => {
    const rows = byStock([entry('2330'), entry('2317', 'technical'), entry('2330', 'technical'), entry('0050')])
    const quotes = new Map([['2330', ready(-0.01)], ['2317', ready(0.03)]])

    expect(shownRows(rows, quotes, 'all', '', 'change').map((row) => row.stockId)).toEqual(['2317', '2330', '0050'])
    expect(shownRows(rows, quotes, 'technical', '', 'code').map((row) => row.stockId)).toEqual(['2317', '2330'])
    expect(shownRows(rows, quotes, 'all', 'name 00', 'code').map((row) => row.stockId)).toEqual(['0050'])
  })
})
