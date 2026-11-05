import { useQuery } from '@tanstack/react-query'
import { apiRequest, strategyResultsKey, useIsSignedIn, type Schemas } from '@/shared/api'

export type StockTechnical = Schemas['StockTechnicalResponse']

/** Daily history settles once a day; a minute keeps repeated visits from recomputing. */
const TECHNICAL_STALE_MS = 60_000

export const technicalKey = (stockId: string) => [...strategyResultsKey, 'technical', stockId] as const

/** The owner's active strategy on this stock, computed by the backend exactly as a run computes it. */
export function useStockTechnical(stockId: string) {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: technicalKey(stockId),
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/stocks/{stock_id}/technical', { params: { stock_id: stockId }, signal }),
    enabled: signedIn,
    staleTime: TECHNICAL_STALE_MS,
  })
}
