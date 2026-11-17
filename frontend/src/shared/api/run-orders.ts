import { useQuery } from '@tanstack/react-query'
import { apiRequest } from './http'
import type { components } from './schema.gen'

/** An order as the trading journal keeps it: what was asked, what the broker made of it, and why. */
export type Order = components['schemas']['Order']

export const runOrdersKey = (runId: string) => ['owner', 'runs', 'orders', runId] as const

/** A run's orders with each one's status and reason; `pollMs` asks again while the run may still place or fill one. */
export function useRunOrders(runId: string, enabled: boolean, pollMs: number | false = false) {
  return useQuery({
    queryKey: runOrdersKey(runId),
    queryFn: ({ signal }) => apiRequest('get', '/v1/runs/{run_id}/orders', { params: { run_id: runId }, signal }),
    enabled,
    refetchInterval: pollMs,
  })
}
