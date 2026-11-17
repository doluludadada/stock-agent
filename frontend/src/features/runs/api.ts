import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { apiRequest, brokersKey, isApiError, runOrdersKey, runResultsKey, useIsSignedIn, type Broker, type Schemas } from '@/shared/api'

export type Run = Schemas['RunResponse']
export type Signal = Schemas['SignalResponse']
export type Follow = Schemas['FollowResponse']
export type FollowItem = Schemas['FollowItem']
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
/** A follow refused outside its window is asked again each minute, so the button opens with the window. */
const WINDOW_POLL_MS = 60_000

export const runKeys = {
  all: ['owner', 'runs'] as const,
  page: (offset: number) => ['owner', 'runs', 'page', offset] as const,
  run: (runId: string) => ['owner', 'runs', 'run', runId] as const,
  signals: (runId: string) => ['owner', 'runs', 'signals', runId] as const,
  orders: runOrdersKey,
  /** Under the run results: a follow's end and a reset of the mock account change what is open to follow. */
  follow: (runId: string) => [...runResultsKey, 'follow', runId] as const,
}

const isLive = (run: Run | undefined) => run?.state === 'running'

/** Reloads what a run may have changed (the account, the holdings, the watchlist) when a poll first sees it ended. */
function reloadResultsOfEnded(client: QueryClient, before: readonly Run[], after: readonly Run[]) {
  const live = new Set(before.filter(isLive).map((run) => run.run_id))
  if (after.some((run) => live.has(run.run_id) && !isLive(run))) void client.invalidateQueries({ queryKey: runResultsKey })
}

/** One page of recorded runs, newest first; one extra row tells whether a next page exists. */
export function useRunsPage(offset: number) {
  const signedIn = useIsSignedIn()
  const client = useQueryClient()
  return useQuery({
    queryKey: runKeys.page(offset),
    queryFn: async ({ signal }) => {
      const before = client.getQueryData<{ runs: Run[] }>(runKeys.page(offset))?.runs ?? []
      const runs = await apiRequest('get', '/v1/runs', { query: { limit: PAGE_SIZE + 1, offset }, signal })
      reloadResultsOfEnded(client, before, runs)
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
      reloadResultsOfEnded(client, before ? [before] : [], [run])
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

/** A 403 can mean the broker's login went down or the user's role changed, so the brokers offered are asked again. */
function askBrokersAgainOnRefusal(client: QueryClient) {
  return (error: Error) => {
    if (isApiError(error, 'forbidden')) void client.invalidateQueries({ queryKey: brokersKey })
  }
}

/** Starts a run; a specific-stock analysis takes its stocks, Buzz and Intraday order on `broker` for the whole run. */
export function useStartRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, stockIds, broker }: { kind: RunKind; stockIds: string[]; broker: Broker }) => {
      switch (kind) {
        case 'full-cycle':
          return apiRequest('post', START_PATHS[kind], { body: { confirm: true } })
        case 'specific-stocks':
          return apiRequest('post', START_PATHS[kind], { body: { confirm: true, stock_ids: stockIds } })
        case 'buzz-scan':
        case 'intraday':
          return apiRequest('post', START_PATHS[kind], { query: { broker }, body: { confirm: true } })
      }
    },
    onError: askBrokersAgainOnRefusal(client),
    onSettled: () => client.invalidateQueries({ queryKey: runKeys.all }),
  })
}

/** Buys `quantity` shares of a stock the specific-stock run reported, on `broker`, as a run of its own whose id the answer carries. */
export function useManualBuy(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ stockId, quantity, broker }: { stockId: string; quantity: number; broker: Broker }) =>
      apiRequest('post', '/v1/runs/{run_id}/manual-buy', { params: { run_id: runId }, query: { broker }, body: { confirm: true, stock_id: stockId, quantity } }),
    onError: askBrokersAgainOnRefusal(client),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: runKeys.all })
      // One stock's BUY can end before its page first asks, so that page never sees it running and reloads nothing.
      void client.invalidateQueries({ queryKey: runResultsKey })
    },
  })
}

/** What a follow of the run into the user's mock account may take now, and every follow of it so far. */
export function useRunFollow(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: runKeys.follow(runId),
    queryFn: ({ signal }) => apiRequest('get', '/v1/runs/{run_id}/follow', { params: { run_id: runId }, signal }),
    enabled,
    refetchInterval: (query) => (query.state.data?.refusal === 'outside_follow_window' ? WINDOW_POLL_MS : false),
  })
}

/** Starts the follow of the run's open decisions as a run of its own, whose id the answer carries. */
export function useFollowRun(runId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiRequest('post', '/v1/runs/{run_id}/follow', { params: { run_id: runId }, body: { confirm: true } }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: runKeys.all })
      // A follow can end before its page first asks, so that page never sees it running and reloads nothing.
      void client.invalidateQueries({ queryKey: runResultsKey })
    },
  })
}
