import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, runResultsKey, useIsSignedIn } from '@/shared/api'
import type { Period } from './model'

export const rankingKeys = {
  latest: ['owner', 'ranking', 'latest'] as const,
  backtest: (period: Period) => ['owner', 'ranking', 'backtest', period.first, period.last] as const,
  formulas: (period: Period) => ['owner', 'ranking', 'formulas', period.first, period.last] as const,
  /** Under the run results: a run's end and a reset of the mock account change what the account holds. */
  follow: [...runResultsKey, 'ranking-follow'] as const,
  /** Under the run results too: a follow's end changes what the schedule still has to follow. */
  schedule: [...runResultsKey, 'ranking-follow-schedule'] as const,
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

/**
 * Every formula of the settings replayed over a period, as the evidence beside the choice. The server replays them one
 * after another and keeps each, so it is asked once the period's backtest has answered. Null asks nothing.
 */
export function useRankingFormulas(period: Period | null) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: rankingKeys.formulas(period ?? { first: '', last: '' }),
    queryFn: ({ signal }) => apiRequest('get', '/v1/rankings/formulas', { query: period!, signal }),
    enabled: signedIn && period !== null,
    staleTime: FRESH_MS,
    gcTime: KEPT_MS,
    placeholderData: keepPreviousData,
  })
}

/** A follow takes seconds; polling every few seconds shows its end soon without loading the server. */
const RUN_POLL_MS = 4000
/** A follow refused outside its window is asked again each minute, so the button opens with the window. */
const WINDOW_POLL_MS = 60_000

/** The viewer's mock account against the latest ranking, and what following the ranking did so far. */
export function useRankingFollow() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: rankingKeys.follow,
    queryFn: ({ signal }) => apiRequest('get', '/v1/rankings/follow', { signal }),
    enabled: signedIn,
    refetchInterval: (query) => (query.state.data?.running ? RUN_POLL_MS : query.state.data?.refusal === 'outside_follow_window' ? WINDOW_POLL_MS : false),
  })
}

/** The viewer's schedule of the follow alone, which the server answers even while no ranking can be made. */
export function useFollowSchedule() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: rankingKeys.schedule,
    queryFn: ({ signal }) => apiRequest('get', '/v1/rankings/follow/schedule', { signal }),
    enabled: signedIn,
  })
}

/** Saves when the site follows the ranking into the mock account by itself, or null for no schedule; the schedule and the block's answer follow it. */
export function useScheduleFollow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (time: string | null) => apiRequest('put', '/v1/rankings/follow/schedule', { body: { confirm: true, time } }),
    onSettled: () => Promise.all([rankingKeys.schedule, rankingKeys.follow].map((queryKey) => client.invalidateQueries({ queryKey }))),
  })
}

/** Starts the follow of the latest ranking into the mock account, as a run whose id the answer carries. */
export function useFollowRanking() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiRequest('post', '/v1/rankings/follow', { body: { confirm: true } }),
    onSettled: () => client.invalidateQueries({ queryKey: runResultsKey }),
  })
}
