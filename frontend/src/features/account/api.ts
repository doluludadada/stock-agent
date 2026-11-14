import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, runResultsKey, useIsSignedIn, type Broker, type Schemas } from '@/shared/api'

export type AccountHistory = Schemas['AccountHistoryResponse']
export type AccountOpening = Schemas['AccountOpening']
export type Trade = Schemas['TradeResponse']
export type BrokerageAccount = Schemas['BrokerageAccountResponse']
export type BrokerageStatement = Schemas['BrokerageStatementResponse']
export type BrokerPosition = Schemas['HeldPositionResponse']
export type BrokerFill = Schemas['BrokerFill']
export type Settlement = Schemas['Settlement']

export const TRADES_PAGE_SIZE = 20

export const accountKeys = {
  history: (asOf: string | null) => [...runResultsKey, 'account', 'mock', 'history', asOf] as const,
  brokerage: [...runResultsKey, 'account', 'brokerage'] as const,
  trades: (broker: Broker) => [...runResultsKey, 'account', broker, 'trades'] as const,
}

/**
 * The mock account now and its equity curve; with `asOf`, also the account at the end of that day. `enabled` holds a
 * lookup back until a day is chosen. It never orders.
 */
export function useAccountHistory(asOf: string | null, enabled = true) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: accountKeys.history(asOf),
    queryFn: ({ signal }) => apiRequest('get', '/v1/account/history', { query: asOf ? { broker: 'mock', as_of: asOf } : { broker: 'mock' }, signal }),
    enabled: signedIn && enabled,
  })
}

/** The site's SinoPac login goes down and comes back while a tab stays open, so the account is asked again like the brokers. */
const BROKERAGE_STALE_MS = 60_000

/**
 * The SinoPac account as the broker reports it now: which server, whether the site's login is up, whether the site
 * lets the user order there, and the statement while the login is up. It only reads.
 */
export function useBrokerageAccount() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: accountKeys.brokerage,
    queryFn: ({ signal }) => apiRequest('get', '/v1/account/brokerage', { signal }),
    enabled: signedIn,
    staleTime: BROKERAGE_STALE_MS,
    refetchOnWindowFocus: true,
    // A refusal is an answer: the page says who the account is for instead of asking again.
    retry: false,
  })
}

/** The `broker` account's trades, newest first, a page at a time; one extra row tells whether a next page exists. */
export function useTrades(broker: Broker) {
  const signedIn = useIsSignedIn()
  return useInfiniteQuery({
    queryKey: accountKeys.trades(broker),
    queryFn: async ({ pageParam, signal }) => {
      const trades = await apiRequest('get', '/v1/account/trades', { query: { limit: TRADES_PAGE_SIZE + 1, offset: pageParam, broker }, signal })
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
