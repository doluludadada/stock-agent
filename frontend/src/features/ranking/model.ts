import type { Schemas } from '@/shared/api'
import { isIsoDate, monthsBefore, periodProblems, type Period, type PeriodProblem } from '@/shared/lib/dates'

export type Ranking = Schemas['Ranking']
export type RankedStock = Schemas['RankedStock']
export type RankingBacktest = Schemas['RankingBacktest']
export type RankingFollow = Schemas['RankingFollowResponse']
export type FormulaEvidence = Schemas['FormulaEvidence']

export type { Period }

export const PRESET_KEYS = ['all', '5Y', '3Y', '1Y'] as const
export type PresetKey = (typeof PRESET_KEYS)[number]

/** The period on screen: a quick one that ends today, or the two days typed. */
export type PeriodChoice = { kind: 'preset'; key: PresetKey } | { kind: 'custom'; period: Period }

export const DEFAULT_CHOICE: PeriodChoice = { kind: 'preset', key: 'all' }

/** Earlier than any daily history the site can hold: the server starts at the first decision it has. */
const BEFORE_ANY_HISTORY = '2000-01-01'
const PRESET_MONTHS: Record<Exclude<PresetKey, 'all'>, number> = { '5Y': 60, '3Y': 36, '1Y': 12 }

function utc(date: string): Date {
  return new Date(`${date}T00:00:00Z`)
}

function iso(date: Date): string {
  return date.toISOString().slice(0, 10)
}

export function periodOf(choice: PeriodChoice, today: string): Period {
  if (choice.kind === 'custom') return choice.period
  return { first: choice.key === 'all' ? BEFORE_ANY_HISTORY : monthsBefore(today, PRESET_MONTHS[choice.key]), last: today }
}

/** The address's period: `?period=` names a quick one, `?first=&last=` two days; anything else is the whole history. */
export function choiceOf(params: URLSearchParams): PeriodChoice {
  const [first, last] = [params.get('first'), params.get('last')]
  if (isIsoDate(first) && isIsoDate(last) && first <= last) return { kind: 'custom', period: { first, last } }
  const key = PRESET_KEYS.find((preset) => preset === params.get('period'))
  return key ? { kind: 'preset', key } : DEFAULT_CHOICE
}

/** The address parameters that name a choice; the whole history needs none. */
export function choiceParams(choice: PeriodChoice): Record<string, string> {
  if (choice.kind === 'custom') return { ...choice.period }
  return choice.key === 'all' ? {} : { period: choice.key }
}

export type ParsedPeriod = { ok: true; period: Period } | { ok: false; problems: Partial<Record<keyof Period, PeriodProblem>> }

/** The two days typed as a period that ends no later than today, or what is wrong at each. */
export function parsePeriod(draft: Period, today: string): ParsedPeriod {
  const problems = periodProblems(draft, { last: today })
  return Object.keys(problems).length === 0 ? { ok: true, period: { first: draft.first, last: draft.last } } : { ok: false, problems }
}

/**
 * The day of the month the ranking decides on or after, read from the decisions seen: every decision falls on that day
 * or later, so the earliest day among them is it once enough months are seen. Null without a decision.
 */
export function decisionDay(decisions: readonly string[]): number | null {
  return decisions.length ? Math.min(...decisions.map((date) => Number(date.slice(8, 10)))) : null
}

export interface NextDecision {
  /** The first weekday on or after the decision day of the month after `decidedOn`; a holiday moves the real one later. */
  on: string
  /** That day has come, so the decision exists once the daily history holds its session. */
  due: boolean
}

export function nextDecision(decidedOn: string, day: number, today: string): NextDecision {
  const next = utc(decidedOn)
  next.setUTCDate(1)
  next.setUTCMonth(next.getUTCMonth() + 1)
  next.setUTCDate(day)
  while (next.getUTCDay() % 6 === 0) next.setUTCDate(next.getUTCDate() + 1)
  const on = iso(next)
  return { on, due: on <= today }
}

/** A time of day as the server writes it, 09:05:00, without its seconds. */
export function clockTime(time: string): string {
  return time.slice(0, 5)
}

/** The first weekday after `date`: the earliest session a decision of that day can be followed on; a holiday moves the real one later. */
export function weekdayAfter(date: string): string {
  const next = utc(date)
  do next.setUTCDate(next.getUTCDate() + 1)
  while (next.getUTCDay() % 6 === 0)
  return iso(next)
}

/** The period that holds the decision of `decidedOn` and the one of the month before, and nothing older. */
export function periodBefore(decidedOn: string): Period {
  const first = utc(decidedOn)
  first.setUTCDate(1)
  first.setUTCMonth(first.getUTCMonth() - 1)
  return { first: iso(first), last: decidedOn }
}

/** The ranking decided just before `decidedOn` among `rankings`; null when it is the oldest or not among them. */
export function rankingBefore(rankings: readonly Ranking[], decidedOn: string): Ranking | null {
  return rankings.findLast((ranking) => ranking.decided_on < decidedOn) ?? null
}

/** What a month's decision changed: the stocks it brought in and the ones it dropped, each in its ranking's order. */
export interface Turnover {
  entered: RankedStock[]
  left: RankedStock[]
  stayed: number
}

export function turnover(previous: Ranking, latest: Ranking): Turnover {
  const before = new Set(previous.stocks.map((stock) => stock.stock_id))
  const now = new Set(latest.stocks.map((stock) => stock.stock_id))
  const entered = latest.stocks.filter((stock) => !before.has(stock.stock_id))
  return { entered, left: previous.stocks.filter((stock) => !now.has(stock.stock_id)), stayed: latest.stocks.length - entered.length }
}

function sessionsOf(curve: Record<string, number>): string[] {
  return Object.keys(curve).sort()
}

/** The sessions a backtest covers: the close of its first decision to its last session. */
export function spanOf(backtest: Pick<RankingBacktest, 'equity_curve'>): Period {
  const sessions = sessionsOf(backtest.equity_curve)
  return { first: sessions[0]!, last: sessions.at(-1)! }
}

/** The decisions that ranked nothing for lack of data, which the backtest sat through in cash: months before the revenue archive begins. */
export function idleDecisions(backtest: Pick<RankingBacktest, 'rankings'>): number {
  return backtest.rankings.filter((ranking) => ranking.stocks.length === 0 && !ranking.holds_cash).length
}

/** The decisions at which the formula's market filter held cash. */
export function cashDecisions(backtest: Pick<RankingBacktest, 'rankings'>): number {
  return backtest.rankings.filter((ranking) => ranking.holds_cash).length
}

/** One session of both curves as what 1 put in at the first decision is worth. */
export interface GrowthPoint {
  date: string
  value: number
  /** Null when the history holds no benchmark. */
  benchmark: number | null
}

export function growthCurve(backtest: Pick<RankingBacktest, 'equity_curve' | 'benchmark_curve'>): GrowthPoint[] {
  return sessionsOf(backtest.equity_curve).map((date) => ({ date, value: backtest.equity_curve[date]!, benchmark: backtest.benchmark_curve[date] ?? null }))
}

export type Scale = 'log' | 'linear'

/** A curve that multiplies several times over flattens everything else on a linear axis, so it starts on a log one. */
const LOG_FROM_RATIO = 4

function extent(points: readonly GrowthPoint[]): [number, number] {
  const values = points.flatMap((point) => (point.benchmark === null ? [point.value] : [point.value, point.benchmark]))
  return [Math.min(...values), Math.max(...values)]
}

export function defaultScale(points: readonly GrowthPoint[]): Scale {
  const [low, high] = extent(points)
  return high / low >= LOG_FROM_RATIO ? 'log' : 'linear'
}

const DECADE_STEPS = [
  [1, 2, 5],
  [1, 1.5, 2, 3, 5, 7],
  [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8],
]
const FEWEST_TICKS = 3

/** The log axis of a curve: its bounds a little outside the values, and round multiples between them as ticks. */
export function logAxis(points: readonly GrowthPoint[]): { domain: [number, number]; ticks: number[] } {
  const [low, high] = extent(points)
  const domain: [number, number] = [low * 0.95, high * 1.05]
  const decades = Array.from({ length: Math.ceil(Math.log10(domain[1])) - Math.floor(Math.log10(domain[0])) + 1 }, (_, index) => 10 ** (Math.floor(Math.log10(domain[0])) + index))
  const within = (steps: number[]) => decades.flatMap((decade) => steps.map((step) => Number((step * decade).toPrecision(2)))).filter((tick) => tick >= domain[0] && tick <= domain[1])
  const ticks = DECADE_STEPS.map(within).find((found) => found.length >= FEWEST_TICKS) ?? within(DECADE_STEPS.at(-1)!)
  return { domain, ticks }
}

export interface YearRow {
  year: number
  ranking: number
  /** Null when the history holds no benchmark. */
  benchmark: number | null
  /** The ranking lost money that year. */
  lost: boolean
  /** The ranking returned less than the benchmark that year. */
  behind: boolean
  /** The first year starts at the first decision and the last one ends at the last session: neither is a whole year. */
  from: string | null
  to: string | null
}

export function yearRows(backtest: Pick<RankingBacktest, 'yearly_returns' | 'benchmark_yearly_returns' | 'equity_curve'>): YearRow[] {
  const span = spanOf(backtest)
  const years = Object.keys(backtest.yearly_returns).map(Number).sort((a, b) => a - b)
  return years.map((year, index) => {
    const ranking = backtest.yearly_returns[year]!
    const benchmark = backtest.benchmark_yearly_returns[year] ?? null
    return {
      year,
      ranking,
      benchmark,
      lost: ranking < 0,
      behind: benchmark !== null && ranking < benchmark,
      from: index === 0 ? span.first : null,
      to: index === years.length - 1 ? span.last : null,
    }
  })
}

/** One monthly decision of a backtest and what holding it did until the next one. */
export interface MonthRow {
  ranking: Ranking
  /** The session it bought at the open of; null when the backtest ends at the decision. */
  heldFrom: string | null
  /** The stocks held from that open: the ranking's that could be bought, then the ones that could not be sold. */
  held: string[]
  /** The next decision's close, or the last session while this decision is the one still held. */
  until: string
  current: boolean
  /** The portfolio's and the benchmark's change from this decision's close to `until`; null over no session or without a benchmark. */
  portfolioReturn: number | null
  benchmarkReturn: number | null
}

/** A backtest's decisions, newest first. */
export function monthRows(backtest: Pick<RankingBacktest, 'rankings' | 'holdings' | 'equity_curve' | 'benchmark_curve'>): MonthRow[] {
  const last = spanOf(backtest).last
  const buys = Object.keys(backtest.holdings).sort()
  const change = (curve: Record<string, number>, from: string, to: string) => {
    const [start, end] = [curve[from], curve[to]]
    return from < to && start !== undefined && end !== undefined ? end / start - 1 : null
  }
  return backtest.rankings
    .map((ranking, index) => {
      const next = backtest.rankings[index + 1]
      const until = next?.decided_on ?? last
      const heldFrom = buys.find((session) => session > ranking.decided_on && session <= until) ?? null
      return {
        ranking,
        heldFrom,
        held: heldFrom ? backtest.holdings[heldFrom]! : [],
        until,
        current: next === undefined,
        portfolioReturn: change(backtest.equity_curve, ranking.decided_on, until),
        benchmarkReturn: change(backtest.benchmark_curve, ranking.decided_on, until),
      }
    })
    .reverse()
}

/** A decision's ranking against what was held from the next open. */
export interface MonthHoldings {
  /** The ranking's stocks, best first; `bought` is false for one that did not trade or opened locked at its limit. */
  ranked: { stock: RankedStock; bought: boolean }[]
  /** Held from an earlier month because they could not be sold that open. */
  carried: string[]
}

export function monthHoldings(row: MonthRow): MonthHoldings {
  const held = new Set(row.held)
  const ranked = new Set(row.ranking.stocks.map((stock) => stock.stock_id))
  return {
    ranked: row.ranking.stocks.map((stock) => ({ stock, bought: row.heldFrom === null || held.has(stock.stock_id) })),
    carried: row.held.filter((stockId) => !ranked.has(stockId)),
  }
}

/** Each stock's name wherever a ranking of the backtest carries it, for the stocks a month lists by code alone. */
export function stockNames(rankings: readonly Ranking[]): Map<string, string> {
  return new Map(rankings.flatMap((ranking) => ranking.stocks.flatMap((stock) => (stock.stock_name ? [[stock.stock_id, stock.stock_name] as const] : []))))
}

/** What the research measured about how far the record can be trusted, in the order a reader should weigh them. */
export const CAVEATS = ['backtest', 'survivors', 'bestOfMany', 'falls', 'lateBuy'] as const
