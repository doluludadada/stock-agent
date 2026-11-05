import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { CHART_RANGES, HISTORY_BARS, sessionDate } from '@/shared/lib/chart-range'
import { useDebouncedValue } from '@/shared/lib/use-debounced-value'
import { apiRequest } from './http'
import type { components } from './schema.gen'

type Schemas = components['schemas']
export type ListedStock = Schemas['ListedStockResponse']
export type DailyBar = Schemas['DailyBarResponse']
export type StockHistory = Schemas['StockHistoryResponse']
export type IndexHistory = Schemas['IndexHistoryResponse']
export type MarketIndex = Schemas['MarketIndex']
export type MarketBreadth = Schemas['MarketBreadth']

const SEARCH_DEBOUNCE_MS = 250
/** The listing changes once per session close; the backend caches it for hours. */
const LISTING_STALE_MS = 5 * 60_000
/** Daily history settles once a day; a minute keeps repeated visits from refetching. */
const HISTORY_STALE_MS = 60_000

/** The public market data: the listing, its latest session, and daily histories. */
export const marketKeys = {
  search: (query: string) => ['public', 'market', 'search', query] as const,
  mostTraded: ['public', 'market', 'most-traded'] as const,
  breadth: ['public', 'market', 'breadth'] as const,
  history: (stockId: string, bars: number) => ['public', 'market', 'history', stockId, bars] as const,
  index: (index: MarketIndex, bars: number) => ['public', 'market', 'index', index, bars] as const,
}

export interface SearchState {
  status: 'idle' | 'loading' | 'error' | 'ready'
  results: { stockId: string; name: string; close: number | null; session: string | null }[]
}

/**
 * The listing search behind the command palette and the target picker: debounced, so typing asks once; a newer query
 * cancels the older request, because the older query loses its last observer and TanStack Query aborts its signal.
 * Until the matches for the text in the box arrive there are none, so Enter never opens a match of an older text.
 */
export function useStockSearch(query: string): SearchState {
  const typed = query.trim()
  const settled = useDebouncedValue(typed, SEARCH_DEBOUNCE_MS)
  const search = useQuery({
    queryKey: marketKeys.search(settled),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks', { query: { query: settled }, signal }),
    enabled: settled.length > 0,
    staleTime: LISTING_STALE_MS,
  })
  if (typed.length === 0) return { status: 'idle', results: [] }
  if (settled !== typed || search.isPending) return { status: 'loading', results: [] }
  if (search.isError) return { status: 'error', results: [] }
  const results = search.data.map((stock) => ({
    stockId: stock.stock_id,
    name: stock.name ?? stock.stock_id,
    close: stock.today?.close ?? null,
    session: stock.today?.ts ?? null,
  }))
  return { status: 'ready', results }
}

export function useMostTraded() {
  return useQuery({
    queryKey: marketKeys.mostTraded,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/most-traded', { signal }),
    staleTime: LISTING_STALE_MS,
  })
}

export function useMarketBreadth() {
  return useQuery({
    queryKey: marketKeys.breadth,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/breadth', { signal }),
    staleTime: LISTING_STALE_MS,
  })
}

export function useStockHistory(stockId: string, bars: number, enabled = true) {
  return useQuery({
    queryKey: marketKeys.history(stockId, bars),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}', { params: { stock_id: stockId }, query: { bars }, signal }),
    staleTime: HISTORY_STALE_MS,
    enabled,
  })
}

export function useIndexHistory(index: MarketIndex, bars: number, enabled = true) {
  return useQuery({
    queryKey: marketKeys.index(index, bars),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/indexes/{index}', { params: { index }, query: { bars }, signal }),
    staleTime: HISTORY_STALE_MS,
    enabled,
  })
}

/** Each code's listing search, under the key the search box uses for the same text. */
function useListings(codes: readonly string[]) {
  return useQueries({
    queries: codes.map((code) => ({
      queryKey: marketKeys.search(code),
      queryFn: ({ signal }: { signal: AbortSignal }) => apiRequest('get', '/v1/market/stocks', { query: { query: code }, signal }),
      staleTime: LISTING_STALE_MS,
    })),
  })
}

/** The listed name of each code, for pages whose data holds codes only, such as the mock account's positions. */
export function useListedNames(codes: readonly string[]): ReadonlyMap<string, string> {
  const listings = useListings(codes)
  return new Map(codes.flatMap((code, index) => {
    const name = listings[index]?.data?.find((stock) => stock.stock_id === code)?.name
    return name ? [[code, name] as const] : []
  }))
}

/** A stock's latest close as the listing reports it, with the session it closed. */
export interface StockQuote {
  close: number
  /** Against the exchange's reference price; against the close before when the listing gave no change. */
  changeRatio: number | null
  /** The session, YYYY-MM-DD in Taipei. */
  session: string
}

export type Loadable<T> = { status: 'loading' } | { status: 'failed' } | { status: 'ready'; value: T }

function quoteOf(bar: DailyBar | null | undefined, previous?: DailyBar): StockQuote | null {
  if (!bar) return null
  const reference = bar.change !== null ? bar.close - bar.change : previous?.close
  return { close: bar.close, changeRatio: reference ? (bar.close - reference) / reference : null, session: sessionDate(bar.ts) }
}

/**
 * The latest close and the month of closes of many stocks, from the shared market data: the quote from the listing,
 * which answers every code at once from the exchange's cached day, or from the stock's daily history when that holds
 * a newer session (the listing updates hours after the history settles); the month from each stock's daily history,
 * under the same key as the stock page, so a stock opened from the list is already loaded. Histories are asked one after
 * another: a cold one goes to Yahoo, which answers a burst of them with empty bars, and the backend then waits hours
 * before asking again. A history already in the cache is read at once; of the others, only the first that has not
 * answered is asked, and its answer re-renders the list, which asks the next.
 */
export function useStockQuotes(codes: readonly string[]) {
  const client = useQueryClient()
  const listings = useListings(codes)
  const answered = codes.map((code) => client.getQueryState(marketKeys.history(code, HISTORY_BARS))?.status)
  const next = answered.findIndex((status) => status !== 'success' && status !== 'error')
  const histories = useQueries({
    queries: codes.map((code, index) => ({
      queryKey: marketKeys.history(code, HISTORY_BARS),
      queryFn: ({ signal }: { signal: AbortSignal }) => apiRequest('get', '/v1/market/stocks/{stock_id}', { params: { stock_id: code }, query: { bars: HISTORY_BARS }, signal }),
      staleTime: HISTORY_STALE_MS,
      enabled: index === next || answered[index] === 'success' || answered[index] === 'error',
    })),
  })

  const quotes = new Map<string, Loadable<StockQuote>>()
  const trends = new Map<string, Loadable<readonly number[]>>()
  codes.forEach((code, index) => {
    const listing = listings[index]!
    const history = histories[index]!
    const bars = history.data?.bars
    const listed = quoteOf(listing.data?.find((stock) => stock.stock_id === code)?.today)
    const charted = bars ? quoteOf(bars.at(-1), bars.at(-2)) : null
    const quote = listed && charted ? (charted.session > listed.session ? charted : listed) : (listed ?? charted)
    quotes.set(code, quote ? { status: 'ready', value: quote } : listing.isPending || history.isPending ? { status: 'loading' } : { status: 'failed' })
    trends.set(code, bars ? { status: 'ready', value: bars.slice(-CHART_RANGES['1M']).map((bar) => bar.close) } : history.isError ? { status: 'failed' } : { status: 'loading' })
  })
  return { quotes, trends }
}
