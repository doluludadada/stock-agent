import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { CHART_RANGES, HISTORY_BARS, sessionDate } from '@/shared/lib/chart-range'
import { useDebouncedValue } from '@/shared/lib/use-debounced-value'
import { useAllows } from './audience'
import { apiRequest } from './http'
import { useIsSignedIn } from './session'
import type { components } from './schema.gen'

type Schemas = components['schemas']
export type ListedStock = Schemas['ListedStockResponse']
export type DailyBar = Schemas['Ohlcv']
export type StockHistory = Schemas['StockHistoryResponse']
export type IndexHistory = Schemas['IndexHistoryResponse']
export type MarketIndex = Schemas['MarketIndex']
export type MarketBreadth = Schemas['MarketBreadth']
export type ArchiveStatus = Schemas['ArchiveStatusResponse']
export type PageQuotes = Schemas['PageQuotesResponse']

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
  archiveStatus: ['public', 'market', 'archive-status'] as const,
  /** Private, so it leaves with the session: only a signed-in viewer makes the site ask the broker. */
  quotes: (codes: readonly string[]) => ['owner', 'market', 'quotes', ...codes] as const,
  indexQuote: (index: MarketIndex) => ['owner', 'market', 'index-quotes', index] as const,
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

/** How many sessions the open-data archive holds and how many the strategies need; it grows once per session. */
export function useArchiveStatus(enabled = true) {
  return useQuery({
    queryKey: marketKeys.archiveStatus,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/archive-status', { signal }),
    staleTime: LISTING_STALE_MS,
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

/** A stock's latest price: its close as the listing reports it with the session it closed, or today's quote so far. */
export interface StockQuote {
  close: number
  /** Against the exchange's reference price; against the close before when the listing gave no change. */
  change: number | null
  changeRatio: number | null
  /** The session, YYYY-MM-DD in Taipei. */
  session: string
  /** When its last trade was, for a quote of a session whose close is not settled yet; null for a settled close. */
  tradedAt: string | null
}

export type Loadable<T> = { status: 'loading' } | { status: 'failed' } | { status: 'ready'; value: T }

function quoteOf(bar: DailyBar | null | undefined, previous?: DailyBar): StockQuote | null {
  if (!bar) return null
  const reference = bar.change !== null ? bar.close - bar.change : previous?.close
  const change = reference ? bar.close - reference : null
  return { close: bar.close, change, changeRatio: change !== null && reference ? change / reference : null, session: sessionDate(bar.ts), tradedAt: null }
}

/**
 * The one rule of what a page shows: today's quote, of the time `quotedAt`, where the settled figure is of an earlier
 * session or there is none, else the settled one. Once a session is settled it replaces that session's last quote.
 */
function showsQuote(settledAt: string | null | undefined, quotedAt: string): boolean {
  return !settledAt || sessionDate(settledAt) < sessionDate(quotedAt)
}

/** The price to show, by that rule: today's quote or the settled close. */
export function latestQuote(settled: StockQuote | null, quoted: DailyBar | null | undefined): StockQuote | null {
  const quote = quoteOf(quoted)
  if (!quote || !quoted || !showsQuote(settled?.session, quoted.ts)) return settled
  return { ...quote, tradedAt: quoted.ts }
}

/**
 * A daily history that ends with today's quote, by the same rule, so its headline and its chart read the quote as the
 * session so far; `tradedAt` is the quote's time where the last bar is the quote, else null.
 */
export function withQuote(bars: readonly DailyBar[], quoted: DailyBar | null | undefined): { bars: readonly DailyBar[]; tradedAt: string | null } {
  if (!quoted || !showsQuote(bars.at(-1)?.ts, quoted.ts)) return { bars, tradedAt: null }
  return { bars: [...bars, quoted], tradedAt: quoted.ts }
}

/** How long a tab waits before it asks for the quotes again: what the server answered, and no timer on a site without quotes now. */
export function quotesPollMs(answer: PageQuotes | undefined): number | false {
  return answer?.refresh ? answer.refresh.seconds * 1000 : false
}

export interface LiveQuotes {
  /** Today's quote of each stock that traded today. */
  bars: ReadonlyMap<string, DailyBar>
  /** A session trades: the quotes change and the tab asks again. */
  live: boolean
  /** Names each stock's last trade, so it differs exactly when the board holds a newer trade of one of them; empty without a quote. */
  trades: string
}

/**
 * How a tab asks the quote board again: after the time the server answers, its interval while the quotes change and a
 * longer one once they stopped, which costs the broker nothing and sees the next session start; only while it is
 * visible, and at once when it comes back into view, whatever the app's default freshness. A failed or refused
 * request is not repeated and leaves the page on its settled closes.
 */
const QUOTE_POLLING = {
  retry: false,
  refetchOnWindowFocus: 'always',
  refetchIntervalInBackground: false,
  refetchInterval: (query: { state: { data: PageQuotes | undefined } }) => quotesPollMs(query.state.data),
} as const

/**
 * Today's realtime quotes of these stocks, from the board every page and user of the site share. Only a signed-in
 * viewer of a site with realtime quotes asks, and the tab asks again by QUOTE_POLLING.
 */
export function useLiveQuotes(codes: readonly string[]): LiveQuotes {
  const signedIn = useIsSignedIn()
  const offered = useAllows('realtime_quotes')
  const ids = [...new Set(codes)].sort()
  const answer = useQuery({
    queryKey: marketKeys.quotes(ids),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/quotes', { query: { ids }, signal }),
    enabled: signedIn && offered && ids.length > 0,
    ...QUOTE_POLLING,
  })
  const bars = new Map<string, DailyBar>()
  for (const [code, bar] of Object.entries(answer.data?.quotes ?? {})) if (bar) bars.set(code, bar)
  const trades = [...bars].map(([code, bar]) => `${code}@${bar.ts}`).sort().join()
  return { bars, live: answer.data?.refresh?.changing === true, trades }
}

/**
 * Today's quote of a market index once its session traded, from the same board and for the same viewers, one request
 * for every panel that shows it. Before the session's first trade, to a visitor and on a site without realtime quotes
 * there is none, and the panels stay on the settled close. A page that does not show the index turns it off.
 */
export function useIndexQuote(index: MarketIndex, enabled = true): { quote: DailyBar | null; live: boolean } {
  const signedIn = useIsSignedIn()
  const offered = useAllows('realtime_quotes')
  const answer = useQuery({
    queryKey: marketKeys.indexQuote(index),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/index-quotes', { query: { indexes: [index] }, signal }),
    enabled: enabled && signedIn && offered,
    ...QUOTE_POLLING,
  })
  return { quote: answer.data?.indexes[index] ?? null, live: answer.data?.refresh?.changing === true }
}

/**
 * The quotes of a page whose own answer the server values at them (My holdings): each time the board holds a newer
 * trade of one of these stocks, the page's own endpoint is asked again, so every figure on screen is the server's at
 * that quote. The page computes none of them.
 */
export function useQuotesThenRefetch(codes: readonly string[], refetch: () => unknown): LiveQuotes {
  const quotes = useLiveQuotes(codes)
  const { trades } = quotes
  useEffect(() => {
    if (trades) void refetch()
  }, [trades, refetch])
  return quotes
}

/**
 * The latest close and the month of closes of many stocks, from the shared market data: the quote from the listing,
 * which answers every code at once from the exchange's cached day, or from the stock's daily history when that holds
 * a newer session (the listing updates hours after the history settles); the month from each stock's daily history,
 * under the same key as the stock page, so a stock opened from the list is already loaded. Histories are asked one after
 * another: a cold one goes to Yahoo, which answers a burst of them with empty bars, and the backend then waits hours
 * before asking again. A history already in the cache is read at once; of the others, only the first that has not
 * answered is asked, and its answer re-renders the list, which asks the next. Without `trends` no history is asked:
 * the quote is the listing's. Either way today's realtime quote replaces a close of an earlier session (latestQuote),
 * and `live` says a session trades.
 */
export function useStockQuotes(codes: readonly string[], { trends: withTrends = true }: { trends?: boolean } = {}) {
  const client = useQueryClient()
  const listings = useListings(codes)
  const { bars: quoted, live } = useLiveQuotes(codes)
  const answered = codes.map((code) => client.getQueryState(marketKeys.history(code, HISTORY_BARS))?.status)
  const next = answered.findIndex((status) => status !== 'success' && status !== 'error')
  const histories = useQueries({
    queries: codes.map((code, index) => ({
      queryKey: marketKeys.history(code, HISTORY_BARS),
      queryFn: ({ signal }: { signal: AbortSignal }) => apiRequest('get', '/v1/market/stocks/{stock_id}', { params: { stock_id: code }, query: { bars: HISTORY_BARS }, signal }),
      staleTime: HISTORY_STALE_MS,
      enabled: withTrends && (index === next || answered[index] === 'success' || answered[index] === 'error'),
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
    const settled = listed && charted ? (charted.session > listed.session ? charted : listed) : (listed ?? charted)
    const quote = latestQuote(settled, quoted.get(code))
    const waiting = listing.isPending || (withTrends && history.isPending)
    quotes.set(code, quote ? { status: 'ready', value: quote } : waiting ? { status: 'loading' } : { status: 'failed' })
    trends.set(code, bars ? { status: 'ready', value: bars.slice(-CHART_RANGES['1M']).map((bar) => bar.close) } : history.isError ? { status: 'failed' } : { status: 'loading' })
  })
  return { quotes, trends, live }
}
