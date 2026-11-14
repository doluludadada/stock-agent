import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, isApiError, runResultsKey, useIsSignedIn } from '@/shared/api'
import type { HoldingEntry, HoldingSource } from './model'

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

/** Why the server kept no entry: a stock the listing does not hold, the listing itself unavailable, or anything else. */
export type EntryRefusal = 'unlisted' | 'listingUnavailable' | 'failed'

const UNLISTED = 'unlisted_stock'

/** The server names an unlisted stock by the `type` of a validation problem, next to the field it is about. */
function namesUnlisted(body: unknown): boolean {
  const detail = typeof body === 'object' && body !== null && 'detail' in body ? body.detail : null
  return Array.isArray(detail) && detail.some((problem: unknown) => typeof problem === 'object' && problem !== null && 'type' in problem && problem.type === UNLISTED)
}

export function entryRefusalOf(error: unknown): EntryRefusal {
  if (isApiError(error, 'invalid') && namesUnlisted(error.body)) return 'unlisted'
  if (isApiError(error) && error.code === 'listing_unavailable') return 'listingUnavailable'
  return 'failed'
}
