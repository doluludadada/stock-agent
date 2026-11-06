import { useQuery } from '@tanstack/react-query'
import { apiRequest, type Schemas } from '@/shared/api'

export type Attribution = Schemas['OpenDataAttribution']

/** The credit is part of the server's settings, which change only with a reload; one answer serves the visit. */
export function useAttribution() {
  return useQuery({
    queryKey: ['public', 'attribution'] as const,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/attribution', { signal }),
    staleTime: Infinity,
  })
}
