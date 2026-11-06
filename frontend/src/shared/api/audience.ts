import { useQuery } from '@tanstack/react-query'
import { apiRequest } from './http'
import type { components } from './schema.gen'

/** Whom the site serves and what that allows, from the server's one table of each audience's capabilities. */
export type Audience = components['schemas']['AudienceResponse']
export type Capability = Exclude<keyof Audience, 'audience'>

/** The audience changes only when the server restarts, so the tab asks once. */
const audienceKey = ['public', 'audience'] as const

export function useAudience() {
  return useQuery({
    queryKey: audienceKey,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/audience', { signal }),
    staleTime: Infinity,
  })
}

/**
 * Whether the site offers what needs this capability: false until the server has said, so a public site never shows,
 * even for a moment, what it refuses. Hiding is never the protection; the server refuses it on every request.
 */
export function allows(audience: Audience | undefined, capability: Capability): boolean {
  return audience?.[capability] === true
}

export function useAllows(capability: Capability): boolean {
  return allows(useAudience().data, capability)
}
