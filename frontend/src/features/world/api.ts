import { useQuery } from '@tanstack/react-query'
import { apiRequest, useIsSignedIn } from '@/shared/api'

/** The server reads the feeds on its own timer; five minutes keeps a revisit from asking for the same answer. */
const WORLD_STALE_MS = 5 * 60_000

/** What the site holds of the world: the indicators, the written briefs and the news. Private, and it asks no feed and no AI. */
export function useWorld() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: ['owner', 'world'] as const,
    queryFn: ({ signal }) => apiRequest('get', '/v1/world', { signal }),
    enabled: signedIn,
    staleTime: WORLD_STALE_MS,
  })
}
