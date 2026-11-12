import { describe, expect, it } from 'vitest'
import {
  choiceOf,
  choiceParams,
  decisionDay,
  defaultScale,
  growthCurve,
  idleDecisions,
  logAxis,
  monthHoldings,
  monthRows,
  nearnessOf,
  nextDecision,
  parsePeriod,
  periodBefore,
  periodOf,
  rankingBefore,
  spanOf,
  stockNames,
  turnover,
  yearRows,
  type Ranking,
  type RankingBacktest,
} from './model'
import recordedBacktest from './test-support/backtest-2023-2024.json'
import recordedLatest from './test-support/latest.json'

/** What the backend answered on the real history for 2023-01-01 to 2024-10-31, and its latest ranking. */
const BACKTEST = recordedBacktest as RankingBacktest
const LATEST = recordedLatest as Ranking

const TODAY = '2026-11-12'

const stock = (stock_id: string, stock_name: string | null = null) => ({
  stock_id,
  stock_name,
  revenue_acceleration: 1.2,
  nearness_to_high: 1,
  acceleration_rank: 0.9,
  nearness_rank: 0.9,
  score: 1.8,
})
const ranking = (decided_on: string, ids: string[]): Ranking => ({ decided_on, revenue_month: '2026-01-01', universe: 700, scored: ids.length ? 690 : 0, stocks: ids.map((id) => stock(id)) })

describe('the period', () => {
  it('asks for the whole history from before any the site can hold, and a quick period back from today', () => {
    expect(periodOf({ kind: 'preset', key: 'all' }, TODAY)).toEqual({ first: '2000-01-01', last: TODAY })
    expect(periodOf({ kind: 'preset', key: '5Y' }, TODAY)).toEqual({ first: '2021-11-12', last: TODAY })
    expect(periodOf({ kind: 'preset', key: '1Y' }, '2024-02-29')).toEqual({ first: '2023-03-01', last: '2024-02-29' })
    expect(periodOf({ kind: 'custom', period: { first: '2023-01-01', last: '2024-10-31' } }, TODAY)).toEqual({ first: '2023-01-01', last: '2024-10-31' })
  })

  it('reads the choice from the address and writes it back, the whole history needing nothing', () => {
    const read = (search: string) => choiceOf(new URLSearchParams(search))
    expect(read('')).toEqual({ kind: 'preset', key: 'all' })
    expect(read('period=3Y')).toEqual({ kind: 'preset', key: '3Y' })
    expect(read('first=2023-01-01&last=2024-10-31')).toEqual({ kind: 'custom', period: { first: '2023-01-01', last: '2024-10-31' } })
    expect(read('period=10Y')).toEqual({ kind: 'preset', key: 'all' })
    expect(read('first=2024-10-31&last=2023-01-01')).toEqual({ kind: 'preset', key: 'all' })
    expect(read('first=2023-13-01&last=2024-10-31')).toEqual({ kind: 'preset', key: 'all' })

    expect(choiceParams({ kind: 'preset', key: 'all' })).toEqual({})
    expect(choiceParams({ kind: 'preset', key: '1Y' })).toEqual({ period: '1Y' })
    expect(choiceParams({ kind: 'custom', period: { first: '2023-01-01', last: '2024-10-31' } })).toEqual({ first: '2023-01-01', last: '2024-10-31' })
  })

  it('holds two typed days at the field that is wrong', () => {
    expect(parsePeriod({ first: '2023-01-01', last: '2024-10-31' }, TODAY)).toEqual({ ok: true, period: { first: '2023-01-01', last: '2024-10-31' } })
    expect(parsePeriod({ first: '', last: '2024-10-31' }, TODAY)).toEqual({ ok: false, problems: { first: 'dateRequired' } })
    expect(parsePeriod({ first: '2024-11-01', last: '2024-10-31' }, TODAY)).toEqual({ ok: false, problems: { last: 'firstAfterLast' } })
    expect(parsePeriod({ first: '2026-12-01', last: '' }, TODAY)).toEqual({ ok: false, problems: { first: 'afterToday', last: 'dateRequired' } })
  })
})

describe('the latest ranking', () => {
  it('reads a stock at its high and one below it', () => {
    expect(nearnessOf(LATEST.stocks[0]!)).toEqual({ atHigh: true })
    const below = nearnessOf(LATEST.stocks[10]!)
    expect(below.atHigh).toBe(false)
    expect(!below.atHigh && below.below).toBeCloseTo(0.020936, 6)
  })

  it('finds the decision day as the earliest day of the month any decision fell on', () => {
    expect(decisionDay(BACKTEST.rankings.map((item) => item.decided_on))).toBe(13)
    expect(decisionDay(['2026-10-14'])).toBe(14)
    expect(decisionDay([])).toBeNull()
  })

  it('expects the next decision on the first weekday from that day of the next month', () => {
    expect(nextDecision('2026-10-13', 13, TODAY)).toEqual({ on: '2026-11-13', due: false })
    expect(nextDecision('2026-10-13', 13, '2026-11-13')).toEqual({ on: '2026-11-13', due: true })
    expect(nextDecision('2026-11-13', 13, '2026-11-20')).toEqual({ on: '2026-12-14', due: false })
    expect(nextDecision('2026-12-14', 13, '2026-12-20')).toEqual({ on: '2027-01-13', due: false })
  })

  it('names the stocks a decision brought in and dropped since the one before', () => {
    const [previous, latest] = [BACKTEST.rankings.at(-2)!, BACKTEST.rankings.at(-1)!]
    expect(periodBefore('2026-10-13')).toEqual({ first: '2026-09-01', last: '2026-10-13' })
    expect(periodBefore('2026-01-13')).toEqual({ first: '2025-12-01', last: '2026-01-13' })
    expect(rankingBefore(BACKTEST.rankings, latest.decided_on)).toBe(previous)
    expect(rankingBefore(BACKTEST.rankings, BACKTEST.rankings[0]!.decided_on)).toBeNull()

    const changed = turnover(previous, latest)
    expect(changed.entered.length).toBe(changed.left.length)
    expect(changed.stayed + changed.entered.length).toBe(latest.stocks.length)
    expect(changed.entered.every((item) => !previous.stocks.some((old) => old.stock_id === item.stock_id))).toBe(true)
    expect(changed.left.every((item) => !latest.stocks.some((now) => now.stock_id === item.stock_id))).toBe(true)

    expect(turnover(ranking('2026-09-14', ['1', '2', '3']), ranking('2026-10-13', ['3', '4', '1']))).toMatchObject({
      entered: [{ stock_id: '4' }],
      left: [{ stock_id: '2' }],
      stayed: 2,
    })
  })
})

describe('the record', () => {
  it('spans the first decision to the last session, with both curves ending at the totals the server answered', () => {
    expect(spanOf(BACKTEST)).toEqual({ first: '2023-01-13', last: '2024-10-30' })
    const points = growthCurve(BACKTEST)
    expect(points).toHaveLength(430)
    expect(points[0]).toEqual({ date: '2023-01-13', value: 1, benchmark: 1 })
    expect(points.at(-1)!.value - 1).toBeCloseTo(BACKTEST.total_return, 5)
    expect(points.at(-1)!.benchmark! - 1).toBeCloseTo(BACKTEST.benchmark_total_return!, 5)
  })

  it('draws a curve without a benchmark alone', () => {
    expect(growthCurve({ equity_curve: { '2026-01-14': 1, '2026-01-13': 1.1 }, benchmark_curve: {} })).toEqual([
      { date: '2026-01-13', value: 1.1, benchmark: null },
      { date: '2026-01-14', value: 1, benchmark: null },
    ])
  })

  it('starts a curve that multiplies on a log axis with round multiples as ticks', () => {
    const tripled = growthCurve(BACKTEST)
    expect(defaultScale(tripled)).toBe('linear')
    expect(logAxis(tripled).ticks).toEqual([1, 1.5, 2, 3])

    const sixtyfold = [
      { date: '2017-07-13', value: 1, benchmark: 1 },
      { date: '2020-03-19', value: 1.4, benchmark: 0.92 },
      { date: '2026-11-11', value: 63.58, benchmark: 6.7 },
    ]
    expect(defaultScale(sixtyfold)).toBe('log')
    const axis = logAxis(sixtyfold)
    expect(axis.ticks).toEqual([1, 2, 5, 10, 20, 50])
    expect(axis.domain[0]).toBeLessThan(0.92)
    expect(axis.domain[1]).toBeGreaterThan(63.58)
  })

  it('sets each year beside the benchmark and marks a losing year and one behind', () => {
    expect(yearRows(BACKTEST)).toEqual([
      { year: 2023, ranking: 0.540644, benchmark: 0.198991, lost: false, behind: false, from: '2023-01-13', to: null },
      { year: 2024, ranking: 0.809645, benchmark: 0.456445, lost: false, behind: false, from: null, to: '2024-10-30' },
    ])
    const rows = yearRows({
      equity_curve: { '2021-12-30': 1, '2022-12-30': 0.75, '2023-12-29': 0.9 },
      yearly_returns: { 2021: 0, 2022: -0.25, 2023: 0.2 },
      benchmark_yearly_returns: { 2021: 0.01, 2022: -0.21, 2023: 0.27 },
    })
    expect(rows.map((row) => [row.year, row.lost, row.behind])).toEqual([
      [2021, false, true],
      [2022, true, true],
      [2023, false, true],
    ])
    expect(yearRows({ equity_curve: { '2023-12-29': 1 }, yearly_returns: { 2023: 0 }, benchmark_yearly_returns: {} })[0]).toMatchObject({ benchmark: null, behind: false })
  })

  it('counts the decisions that ranked nothing', () => {
    expect(idleDecisions(BACKTEST)).toBe(0)
    expect(idleDecisions({ rankings: [ranking('2017-07-13', []), ranking('2017-08-14', []), ranking('2018-01-15', ['1'])] })).toBe(2)
  })
})

describe('past months', () => {
  const rows = monthRows(BACKTEST)

  it('lists every decision newest first with the session it bought at and what it held', () => {
    expect(rows).toHaveLength(22)
    expect(rows[0]).toMatchObject({ heldFrom: '2024-10-15', until: '2024-10-30', current: true })
    expect(rows[0]!.ranking.decided_on).toBe('2024-10-14')
    expect(rows.at(-1)).toMatchObject({ heldFrom: '2023-01-16', until: '2023-02-13', current: false })
    expect(rows.at(-1)!.held).toEqual(BACKTEST.holdings['2023-01-16'])
  })

  it('measures each month from its decision to the next, so the months compound to the whole record', () => {
    const compounded = rows.reduce((value, row) => value * (1 + row.portfolioReturn!), 1)
    expect(compounded - 1).toBeCloseTo(BACKTEST.total_return, 4)
    const benchmark = rows.reduce((value, row) => value * (1 + row.benchmarkReturn!), 1)
    expect(benchmark - 1).toBeCloseTo(BACKTEST.benchmark_total_return!, 4)
  })

  it('tells a ranked stock that was not bought from one carried because it could not be sold', () => {
    const october = monthHoldings(rows[0]!)
    expect(october.ranked).toHaveLength(20)
    expect(october.ranked.every((item) => item.bought)).toBe(true)
    expect(october.carried).toEqual(['8249'])

    const february = monthHoldings(rows.find((row) => row.heldFrom === '2023-02-14')!)
    expect(february.ranked.filter((item) => !item.bought)).toHaveLength(1)
    expect(february.carried).toEqual([])
  })

  it('has no return and nothing held for a decision the backtest ends at', () => {
    const [only] = monthRows({ rankings: [ranking('2026-11-13', ['1', '2'])], holdings: {}, equity_curve: { '2026-11-13': 1 }, benchmark_curve: { '2026-11-13': 1 } })
    expect(only).toMatchObject({ heldFrom: null, held: [], current: true, portfolioReturn: null, benchmarkReturn: null })
    expect(monthHoldings(only!).ranked.every((item) => item.bought)).toBe(true)
  })

  it('names a stock from any ranking that carries its name', () => {
    expect(stockNames(BACKTEST.rankings).size).toBe(0)
    expect(stockNames([{ ...ranking('2026-10-13', []), stocks: [stock('2330', '台積電'), stock('2317')] }])).toEqual(new Map([['2330', '台積電']]))
  })
})
