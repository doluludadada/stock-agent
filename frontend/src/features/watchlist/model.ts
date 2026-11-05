import type { Loadable, Schemas, StockQuote } from '@/shared/api'
import type { WatchlistEntry } from './api'

export type WatchlistType = Schemas['WatchlistType']

/** One stock on the list, with every way it got there: added by hand, by a technical run or by a buzz scan. */
export interface WatchRow {
  stockId: string
  name: string | null
  entries: WatchlistEntry[]
}

export function byStock(entries: readonly WatchlistEntry[]): WatchRow[] {
  const rows = new Map<string, WatchRow>()
  for (const entry of entries) {
    const row = rows.get(entry.stock_id) ?? { stockId: entry.stock_id, name: entry.name ?? null, entries: [] }
    row.entries.push(entry)
    rows.set(entry.stock_id, row)
  }
  return [...rows.values()]
}

export type Quotes = ReadonlyMap<string, Loadable<StockQuote>>

export type SourceFilter = 'all' | WatchlistType
export const SOURCE_FILTERS: readonly SourceFilter[] = ['all', 'manual', 'technical', 'buzz']

export type SortKey = 'change' | 'code' | 'added'
export const SORT_KEYS: readonly SortKey[] = ['change', 'code', 'added']

function quoteOf(quotes: Quotes, row: WatchRow): StockQuote | null {
  const state = quotes.get(row.stockId)
  return state?.status === 'ready' ? state.value : null
}

const addedOf = (row: WatchRow): string => row.entries.map((entry) => entry.created_at).sort().at(-1) ?? ''

/** The newest session any quote closed: the one the list's summary describes. */
export function latestSession(quotes: Quotes): string | null {
  const sessions = [...quotes.values()].flatMap((state) => (state.status === 'ready' ? [state.value.session] : []))
  return sessions.length === 0 ? null : sessions.reduce((latest, session) => (session > latest ? session : latest))
}

/**
 * The rows a filter and a search keep, in the chosen order: the day's change strongest first (stocks without a quote
 * last), the code, or the newest addition first.
 */
export function shownRows(rows: readonly WatchRow[], quotes: Quotes, filter: SourceFilter, query: string, sort: SortKey): WatchRow[] {
  const needle = query.trim().toLowerCase()
  const kept = rows.filter(
    (row) =>
      (filter === 'all' || row.entries.some((entry) => entry.watchlist_type === filter)) &&
      (!needle || row.stockId.toLowerCase().startsWith(needle) || (row.name ?? '').toLowerCase().includes(needle)),
  )
  const change = (row: WatchRow) => quoteOf(quotes, row)?.changeRatio ?? -Infinity
  const order: Record<SortKey, (a: WatchRow, b: WatchRow) => number> = {
    change: (a, b) => change(b) - change(a) || a.stockId.localeCompare(b.stockId),
    code: (a, b) => a.stockId.localeCompare(b.stockId),
    added: (a, b) => addedOf(b).localeCompare(addedOf(a)) || a.stockId.localeCompare(b.stockId),
  }
  return [...kept].sort(order[sort])
}

export interface Mover {
  row: WatchRow
  changeRatio: number
}

export interface WatchSummary {
  /** The session the figures describe; null before any quote arrives. */
  session: string | null
  up: number
  flat: number
  down: number
  /** The mean change of the stocks that closed in that session. */
  average: number | null
  best: Mover | null
  worst: Mover | null
  /** Stocks whose latest close is from an earlier session: listed with their date, never averaged in. */
  earlier: number
}

/**
 * How the list did in its latest session: how many rose and fell, the average move, the strongest and the weakest.
 * Only stocks that closed in that session count, so a stock whose close is a day older never mixes in.
 */
export function daySummary(rows: readonly WatchRow[], quotes: Quotes): WatchSummary {
  const session = latestSession(new Map(rows.flatMap((row) => (quotes.has(row.stockId) ? [[row.stockId, quotes.get(row.stockId)!]] : []))))
  const quoted = rows.flatMap((row) => {
    const quote = quoteOf(quotes, row)
    return quote ? [{ row, quote }] : []
  })
  const moved: Mover[] = quoted.flatMap(({ row, quote }) => (quote.session === session && quote.changeRatio !== null ? [{ row, changeRatio: quote.changeRatio }] : []))
  const ranked = [...moved].sort((a, b) => b.changeRatio - a.changeRatio)
  const best = ranked[0]
  const worst = ranked.at(-1)
  return {
    session,
    up: moved.filter((item) => item.changeRatio > 0).length,
    flat: moved.filter((item) => item.changeRatio === 0).length,
    down: moved.filter((item) => item.changeRatio < 0).length,
    average: moved.length === 0 ? null : moved.reduce((total, item) => total + item.changeRatio, 0) / moved.length,
    best: best && best.changeRatio > 0 ? best : null,
    worst: worst && worst.changeRatio < 0 ? worst : null,
    earlier: quoted.filter(({ quote }) => quote.session !== session).length,
  }
}
