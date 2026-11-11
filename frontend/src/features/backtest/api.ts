import { useMutation, useMutationState, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, isApiError, strategyResultsKey, useIsSignedIn } from '@/shared/api'
import type { BacktestInputs } from './model'

export const backtestKeys = {
  /** Names the active strategy, so a strategy save or switch asks again. */
  options: [...strategyResultsKey, 'backtest-options'] as const,
  list: ['owner', 'backtests', 'list'] as const,
  detail: (id: string) => ['owner', 'backtests', 'detail', id] as const,
}

const RUN_KEY = ['owner', 'backtests', 'run'] as const

/** The strategy a backtest would replay and the longest period allowed now; `inputs` is null while the history is too short. */
export function useBacktestOptions() {
  const signedIn = useIsSignedIn()
  return useQuery({ queryKey: backtestKeys.options, queryFn: ({ signal }) => apiRequest('get', '/v1/backtests/options', { signal }), enabled: signedIn })
}

/** The user's saved backtests, newest first, without their days and trades. */
export function useBacktests() {
  const signedIn = useIsSignedIn()
  return useQuery({ queryKey: backtestKeys.list, queryFn: ({ signal }) => apiRequest('get', '/v1/backtests', { signal }), enabled: signedIn })
}

/** One saved backtest with its days and trades. A saved backtest never changes, so it is asked once. */
export function useBacktest(id: string | null) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: backtestKeys.detail(id ?? ''),
    queryFn: ({ signal }) => apiRequest('get', '/v1/backtests/{backtest_id}', { params: { backtest_id: id ?? '' }, signal }),
    enabled: signedIn && id !== null,
    staleTime: Infinity,
    retry: (count, error) => !isApiError(error, 'notFound') && count < 2,
  })
}

/**
 * Runs and saves one backtest. The answer can take tens of seconds, so it lands in the cache and the saved list even
 * when the page was left meanwhile. A period refusal asks the options again: the days available have changed.
 */
export function useRunBacktest() {
  const client = useQueryClient()
  return useMutation({
    mutationKey: RUN_KEY,
    mutationFn: (inputs: BacktestInputs) => apiRequest('post', '/v1/backtests', { body: { confirm: true, inputs } }),
    onSuccess: (backtest) => {
      client.setQueryData(backtestKeys.detail(backtest.backtest_id), backtest)
      void client.invalidateQueries({ queryKey: backtestKeys.list })
    },
    onError: (error) => {
      if (isApiError(error) && error.code === 'backtest_period_unavailable') void client.invalidateQueries({ queryKey: backtestKeys.options })
    },
  })
}

/** When the backtest still running was started, in epoch milliseconds; null when none runs. It outlives the page that started it. */
export function useRunningSince(): number | null {
  const started = useMutationState({ filters: { mutationKey: RUN_KEY, status: 'pending' }, select: (mutation) => mutation.state.submittedAt })
  return started.at(-1) ?? null
}

export function useDeleteBacktest() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiRequest('post', '/v1/backtests/{backtest_id}/delete', { params: { backtest_id: id }, body: { confirm: true } }),
    onSuccess: (_, id) => client.removeQueries({ queryKey: backtestKeys.detail(id) }),
    // A backtest already gone answers 404; the list then loads without it.
    onSettled: () => client.invalidateQueries({ queryKey: backtestKeys.list }),
  })
}
