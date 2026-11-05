import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { apiRequest, runResultsKey, useIsSignedIn, type Schemas } from '@/shared/api'

export type AccountHistory = Schemas['AccountHistoryResponse']

export const accountKeys = { history: (asOf: string | null) => [...runResultsKey, 'account', 'history', asOf] as const }

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
