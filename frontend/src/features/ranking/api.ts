import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { apiRequest, useIsSignedIn } from '@/shared/api'
import type { Period } from './model'

export const rankingKeys = {
  latest: ['owner', 'ranking', 'latest'] as const,
  backtest: (period: Period) => ['owner', 'ranking', 'backtest', period.first, period.last] as const,
}

/**
 * An answer changes only when the daily history holds another session, and one takes seconds to compute, so a page
 * opened again within the hour shows what it already has and asks again only after ten minutes.
 */
const FRESH_MS = 10 * 60_000
const KEPT_MS = 60 * 60_000

/** The ranking at the latest decision the daily history holds. */
export function useLatestRanking() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: rankingKeys.latest,
    queryFn: ({ signal }) => apiRequest('get', '/v1/rankings/latest', { signal }),
    enabled: signedIn,
    staleTime: FRESH_MS,
    gcTime: KEPT_MS,
  })
}

/**
 * The ranking replayed over a period, kept by its two days so a period seen before shows at once. With `keepShown` the
 * period before stays on screen while the next one is computed. Null asks nothing.
 */
export function useRankingBacktest(period: Period | null, { keepShown = false }: { keepShown?: boolean } = {}) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: rankingKeys.backtest(period ?? { first: '', last: '' }),
    queryFn: ({ signal }) => apiRequest('get', '/v1/rankings/backtest', { query: period!, signal }),
    enabled: signedIn && period !== null,
    staleTime: FRESH_MS,
    gcTime: KEPT_MS,
    placeholderData: keepShown ? keepPreviousData : undefined,
  })
}
