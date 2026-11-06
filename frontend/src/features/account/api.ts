import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, runResultsKey, useIsSignedIn, type Schemas } from '@/shared/api'

export type AccountHistory = Schemas['AccountHistoryResponse']
export type AccountOpening = Schemas['AccountOpening']
export type Trade = Schemas['TradeResponse']

export const TRADES_PAGE_SIZE = 20

export const accountKeys = {
  history: (asOf: string | null) => [...runResultsKey, 'account', 'history', asOf] as const,
  trades: [...runResultsKey, 'account', 'trades'] as const,
}

/** The account now, its equity curve and, when asked, the account at the end of a past day. It never orders. */
export function useAccountHistory(asOf: string | null) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: accountKeys.history(asOf),
    queryFn: ({ signal }) => apiRequest('get', '/v1/account/history', { query: asOf ? { as_of: asOf } : {}, signal }),
    enabled: signedIn,
    /** Asking for another day keeps the page on screen until the answer arrives. */
    placeholderData: keepPreviousData,
  })
}

/** The trades since the account opened, newest first, a page at a time; one extra row tells whether a next page exists. */
export function useTrades() {
  const signedIn = useIsSignedIn()
  return useInfiniteQuery({
    queryKey: accountKeys.trades,
    queryFn: async ({ pageParam, signal }) => {
      const trades = await apiRequest('get', '/v1/account/trades', { query: { limit: TRADES_PAGE_SIZE + 1, offset: pageParam }, signal })
      return { trades: trades.slice(0, TRADES_PAGE_SIZE), next: trades.length > TRADES_PAGE_SIZE ? pageParam + TRADES_PAGE_SIZE : null }
    },
    initialPageParam: 0,
    getNextPageParam: (page) => page.next,
    enabled: signedIn,
  })
}

/** Opens the mock account again with `initialCash` and no positions; everything a run changes loads again. */
export function useResetAccount() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (initialCash: number) => apiRequest('post', '/v1/account/reset', { body: { confirm: true, initial_cash: initialCash } }),
    onSuccess: () => client.invalidateQueries({ queryKey: runResultsKey }),
  })
}
