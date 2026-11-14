import { useQuery } from '@tanstack/react-query'
import { apiRequest } from './http'
import { SITE_STATE_STALE_MS } from './query-keys'
import type { components } from './schema.gen'

/** Whom the site serves and what that allows, from the server's one table of each audience's capabilities. */
export type Audience = components['schemas']['AudienceResponse']
/** What the audience allows or not; `order_pricing` says how the site prices an order instead. */
export type Capability = { [K in keyof Audience]: Audience[K] extends boolean ? K : never }[keyof Audience]

const audienceKey = ['public', 'audience'] as const
const AUDIENCE_POLL_MS = 5 * 60_000

/**
 * The audience changes only when the server restarts, but `realtime_quotes` also needs the runtime's Shioaji login,
 * which can go down and come back at a reload or at the server's next daily collection. So the tab asks again when it
 * is back in focus a minute later, and every few minutes while it stays open.
 */
export function useAudience() {
  return useQuery({
    queryKey: audienceKey,
    queryFn: ({ signal }) => apiRequest('get', '/v1/market/audience', { signal }),
    staleTime: SITE_STATE_STALE_MS,
    refetchOnWindowFocus: true,
    refetchInterval: AUDIENCE_POLL_MS,
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
