import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, isApiError, runResultsKey, session, useIsSignedIn, type Schemas } from '@/shared/api'

export type WatchlistEntry = Schemas['WatchlistEntryResponse']

export const watchlistKeys = { all: [...runResultsKey, 'watchlist'] as const }

export function useWatchlistEntries() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: watchlistKeys.all,
    queryFn: ({ signal }) => apiRequest('get', '/v1/watchlist', { signal }),
    enabled: signedIn,
  })
}

/** One watched stock, however it got on the list. */
export interface WatchedStock {
  stockId: string
  name: string | null
}

const NO_STOCKS: readonly WatchedStock[] = []

function watchedStocks(entries: readonly WatchlistEntry[]): WatchedStock[] {
  const names = new Map(entries.map((entry) => [entry.stock_id, entry.name ?? null]))
  return [...names].map(([stockId, name]) => ({ stockId, name }))
}

/**
 * The stocks on the user's watchlist, each once, for a route to hand to a page of another feature. Asked only while
 * `shown`, which the route sets where the site shows the viewer the watchlist; empty until then and until it answers.
 */
export function useWatchedStocks(shown: boolean): readonly WatchedStock[] {
  const signedIn = useIsSignedIn()
  const { data } = useQuery({
    queryKey: watchlistKeys.all,
    queryFn: ({ signal }) => apiRequest('get', '/v1/watchlist', { signal }),
    enabled: signedIn && shown,
    select: watchedStocks,
  })
  return data ?? NO_STOCKS
}

type Change = { action: 'add' | 'remove'; stockIds: string[] }

/**
 * Adds to or removes from the MANUAL watchlist. The cached list changes at once, and a refused change undoes only its
 * own entries, so another change still in flight stays shown; the server's list replaces it after.
 */
export function useWatchlistChange() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ action, stockIds }: Change): Promise<unknown> =>
      action === 'add'
        ? apiRequest('post', '/v1/watchlist/manual', { body: { confirm: true, stock_ids: stockIds } })
        : apiRequest('post', '/v1/watchlist/manual/remove', { body: { confirm: true, stock_ids: stockIds } }),
    onMutate: async ({ action, stockIds }) => {
      await client.cancelQueries({ queryKey: watchlistKeys.all })
      const previous = client.getQueryData<WatchlistEntry[]>(watchlistKeys.all) ?? []
      const removed = previous.filter((entry) => entry.watchlist_type === 'manual' && stockIds.includes(entry.stock_id))
      const added = stockIds.filter((stockId) => !isManuallyWatched(previous, stockId))
      const now = new Date().toISOString()
      client.setQueryData<WatchlistEntry[]>(watchlistKeys.all, (entries = []) =>
        action === 'remove'
          ? entries.filter((entry) => !(entry.watchlist_type === 'manual' && stockIds.includes(entry.stock_id)))
          : [
              ...entries,
              ...stockIds
                .filter((stockId) => !isManuallyWatched(entries, stockId))
                .map((stockId) => ({ stock_id: stockId, name: null, watchlist_type: 'manual' as const, created_at: now, expires_at: null })),
            ],
      )
      return { removed, added }
    },
    onError: (error, { action }, context) => {
      // An ended session already dropped the user's cache; putting the old list back would show it signed out.
      if (isApiError(error, 'unauthorized') || session.current().status !== 'signedIn' || !context) return
      client.setQueryData<WatchlistEntry[]>(watchlistKeys.all, (entries = []) =>
        action === 'add'
          ? entries.filter((entry) => !(entry.watchlist_type === 'manual' && context.added.includes(entry.stock_id)))
          : [...entries, ...context.removed.filter((entry) => !isManuallyWatched(entries, entry.stock_id))],
      )
    },
    onSettled: () => client.invalidateQueries({ queryKey: watchlistKeys.all }),
  })
}

export function isManuallyWatched(entries: readonly WatchlistEntry[] | undefined, stockId: string): boolean {
  return (entries ?? []).some((entry) => entry.stock_id === stockId && entry.watchlist_type === 'manual')
}
