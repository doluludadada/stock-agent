import { skipToken, useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, strategyResultsKey, useIsSignedIn, type Schemas } from '@/shared/api'

export type ValuationReport = Schemas['ValuationReportResponse']
export type ValuationScan = Schemas['ValuationScanResponse']
export type MarketValuation = Schemas['MarketValuationResponse']
export type Explanation = Schemas['ValuationExplanationResponse']

/** The server keeps a loaded market for 15 minutes; asking more often only repeats its answer. */
const MARKET_STALE_MS = 5 * 60_000

export const valuationKeys = {
  market: ['owner', 'valuation', 'market'] as const,
  stocks: (stockIds: string[], targetPe: number | null) => ['owner', 'valuation', 'stocks', stockIds.join(','), targetPe] as const,
  /** The technical step runs the saved strategy, so the scan lives with the other strategy results. */
  scan: (targetPe: number, minUndervaluation: number, technical: boolean) => [...strategyResultsKey, 'valuation-scan', targetPe, minUndervaluation, technical] as const,
  explanations: ['owner', 'valuation', 'explanation'] as const,
  explanation: (stockId: string, targetPe: number) => ['owner', 'valuation', 'explanation', stockId, targetPe] as const,
}

export function useMarketValuation() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: valuationKeys.market,
    queryFn: ({ signal }) => apiRequest('get', '/v1/valuation/market', { signal }),
    enabled: signedIn,
    staleTime: MARKET_STALE_MS,
  })
}

export function useValuedStocks(request: { stockIds: string[]; targetPe: number | null } | null) {
  return useQuery({
    queryKey: valuationKeys.stocks(request?.stockIds ?? [], request?.targetPe ?? null),
    queryFn: ({ signal }) =>
      apiRequest('get', '/v1/valuation/stocks', {
        
        query: { stock_ids: request!.stockIds, ...(request!.targetPe === null ? {} : { target_pe: request!.targetPe }) },
        signal,
      }),
    enabled: request !== null,
    staleTime: MARKET_STALE_MS,
  })
}

export function useValuationScan(request: { targetPe: number; minUndervaluation: number; technical: boolean } | null) {
  return useQuery({
    queryKey: valuationKeys.scan(request?.targetPe ?? 0, request?.minUndervaluation ?? 0, request?.technical ?? false),
    queryFn: ({ signal }) =>
      apiRequest('get', '/v1/valuation/scan', {
        
        query: { target_pe: request!.targetPe, min_undervaluation: request!.minUndervaluation, technical: request!.technical },
        signal,
      }),
    enabled: request !== null,
    staleTime: MARKET_STALE_MS,
  })
}

/**
 * One paid AI call per click; never retried and never fetched by a render, a refocus or a refresh. The answer stays in
 * the cache under the stock and target P/E, and a call in flight is seen by every card of that stock, so a tab switch,
 * a rescan or the technical step neither loses the answer nor offers a second call.
 */
export function useExplanation(stockId: string, targetPe: number) {
  const client = useQueryClient()
  const key = valuationKeys.explanation(stockId, targetPe)
  const stored = useQuery<Explanation>({ queryKey: key, queryFn: skipToken, staleTime: Infinity, gcTime: Infinity })
  const pending = useIsMutating({ mutationKey: key }) > 0
  const mutation = useMutation({
    mutationKey: key,
    mutationFn: () => apiRequest('post', '/v1/valuation/explanation', { body: { confirm: true, stock_id: stockId, target_pe: targetPe } }),
    onSuccess: (explanation) => client.setQueryData<Explanation>(key, explanation),
  })
  return { explanation: stored.data, pending, ask: mutation.mutate }
}

/** True while any explanation is being written. */
export function useExplaining() {
  return useIsMutating({ mutationKey: valuationKeys.explanations }) > 0
}
