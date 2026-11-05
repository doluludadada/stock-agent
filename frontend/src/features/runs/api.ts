import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, runResultsKey, useIsSignedIn, type Schemas } from '@/shared/api'

export type Run = Schemas['RunResponse']
export type Signal = Schemas['SignalResponse']
export type Order = Schemas['Order']
const START_PATHS = {
  'full-cycle': '/v1/runs/full-cycle',
  'specific-stocks': '/v1/runs/specific-stocks',
  'buzz-scan': '/v1/runs/buzz-scan',
  intraday: '/v1/runs/intraday',
} as const
export type RunKind = keyof typeof START_PATHS

export const PAGE_SIZE = 15
/** A run takes minutes; polling every few seconds shows its end soon without loading the server. */
const POLL_MS = 4000

export const runKeys = {
  all: ['owner', 'runs'] as const,
  page: (offset: number) => ['owner', 'runs', 'page', offset] as const,
  run: (runId: string) => ['owner', 'runs', 'run', runId] as const,
  signals: (runId: string) => ['owner', 'runs', 'signals', runId] as const,
  orders: (runId: string) => ['owner', 'runs', 'orders', runId] as const,
}

const isLive = (run: Run | undefined) => run?.state === 'running'

/** One page of recorded runs, newest first; one extra row tells whether a next page exists. */
export function useRunsPage(offset: number) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: runKeys.page(offset),
    queryFn: async ({ signal }) => {
      const runs = await apiRequest('get', '/v1/runs', { query: { limit: PAGE_SIZE + 1, offset }, signal })
      return { runs: runs.slice(0, PAGE_SIZE), hasNext: runs.length > PAGE_SIZE }
    },
    enabled: signedIn,
    refetchInterval: (query) => (query.state.data?.runs.some(isLive) ? POLL_MS : false),
  })
}

/**
 * The run's state, polled while it runs; polling stops at its end, when the page closes, and in a background tab. The
 * poll that sees it end reloads the account and the watchlist the run may have changed.
 */
export function useRun(runId: string) {
  const signedIn = useIsSignedIn()
  const client = useQueryClient()
  return useQuery({
    queryKey: runKeys.run(runId),
    queryFn: async ({ signal }) => {
      const before = client.getQueryData<Run>(runKeys.run(runId))
      const run = await apiRequest('get', '/v1/runs/{run_id}', { params: { run_id: runId }, signal })
      if (isLive(before) && !isLive(run)) void client.invalidateQueries({ queryKey: runResultsKey })
      return run
    },
    enabled: signedIn,
    refetchInterval: (query) => (isLive(query.state.data) ? POLL_MS : false),
  })
}

export function useRunSignals(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: runKeys.signals(runId),
    queryFn: ({ signal }) => apiRequest('get', '/v1/runs/{run_id}/signals', { params: { run_id: runId }, signal }),
    enabled,
  })
}

export function useRunOrders(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: runKeys.orders(runId),
    queryFn: ({ signal }) => apiRequest('get', '/v1/runs/{run_id}/orders', { params: { run_id: runId }, signal }),
    enabled,
  })
}

export function useStartRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, stockIds = [] }: { kind: RunKind; stockIds?: string[] }) =>
      kind === 'specific-stocks'
        ? apiRequest('post', START_PATHS[kind], { body: { confirm: true, stock_ids: stockIds } })
        : apiRequest('post', START_PATHS[kind], { body: { confirm: true } }),
    onSettled: () => client.invalidateQueries({ queryKey: runKeys.all }),
  })
}
