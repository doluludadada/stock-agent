import { useQuery } from '@tanstack/react-query'
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
