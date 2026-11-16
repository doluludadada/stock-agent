import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { apiRequest, isApiError, runResultsKey, useIsSignedIn, useQuotesThenRefetch } from '@/shared/api'
import { quotedHoldings, type HoldingEntry, type Holdings, type HoldingSource, type QuotedHoldings } from './model'

/** The holdings read the mock account, which a run's end changes, so they reload with everything a run leaves. */
export const holdingsKeys = {
  all: [...runResultsKey, 'holdings'] as const,
  of: (sources: readonly HoldingSource[] | null) => [...runResultsKey, 'holdings', sources ?? 'offered'] as const,
}

/**
 * The user's holdings as one portfolio, from the sources named or, with null, from every source the site shows the
 * user. A refusal is an answer (the ranking holds no decision yet), so it is not asked again; a change of sources
 * keeps the portfolio before on screen until the next one arrives.
 */
export function useHoldings(sources: readonly HoldingSource[] | null) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: holdingsKeys.of(sources),
    queryFn: ({ signal }) => apiRequest('get', '/v1/holdings', { query: sources ? { sources: [...sources] } : {}, signal }),
    enabled: signedIn,
    placeholderData: keepPreviousData,
    retry: false,
  })
}

/**
 * What the server valued at today's quotes in the portfolio, and whether a session trades. While the site has quotes
 * the portfolio is asked again (`refetch`) each time the board holds a newer trade of a held stock.
 */
export function useQuotedHoldings(holdings: Holdings, refetch: () => unknown): QuotedHoldings & { live: boolean } {
  const codes = useMemo(() => holdings.holdings.map((row) => row.position.stock_id), [holdings])
  const { bars, live } = useQuotesThenRefetch(codes, refetch)
  return { ...quotedHoldings(holdings, bars), live }
}

/** Keeps a hand-entered holding, replacing the user's earlier entry of the same stock. It orders nothing. */
export function useEnterHolding() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (entry: HoldingEntry) => apiRequest('post', '/v1/holdings/manual', { body: entry }),
    onSuccess: () => client.invalidateQueries({ queryKey: holdingsKeys.all }),
  })
}

/** Takes the user's hand-entered holding of a stock off the list. */
export function useRemoveHolding() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (stockId: string) => apiRequest('post', '/v1/holdings/manual/remove', { body: { confirm: true, stock_id: stockId } }),
    onSuccess: () => client.invalidateQueries({ queryKey: holdingsKeys.all }),
  })
}

/** Why the server kept no entry: a stock the listing does not hold, which the form says at the stock, or anything else. */
export type EntryRefusal = 'unlisted' | 'failed'

const UNLISTED = 'unlisted_stock'

/** The server names an unlisted stock by the `type` of a validation problem, next to the field it is about. */
function namesUnlisted(body: unknown): boolean {
  const detail = typeof body === 'object' && body !== null && 'detail' in body ? body.detail : null
  return Array.isArray(detail) && detail.some((problem: unknown) => typeof problem === 'object' && problem !== null && 'type' in problem && problem.type === UNLISTED)
}

export function entryRefusalOf(error: unknown): EntryRefusal {
  if (isApiError(error, 'invalid') && namesUnlisted(error.body)) return 'unlisted'
  return 'failed'
}
