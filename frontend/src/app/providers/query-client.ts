import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { authStatusKey, isApiError, session } from '@/shared/api'

const DEFAULT_STALE_MS = 30_000

/**
 * Server state lives in one query cache. Query keys start with their scope ('public', 'owner' or 'admin'), so the
 * private scopes' cached data is dropped the moment another user signs in, the user signs out or the server ends the
 * session, and the administrator's when a role changes: one user's answers never show to the next.
 */
export function createQueryClient(): QueryClient {
  /** The server refused a feature this tab still showed: the administrator hid it since, so the tab asks what shows now. */
  const rereadHiddenFeatures = (error: unknown) => {
    if (isApiError(error) && error.code === 'feature_hidden') void client.invalidateQueries({ queryKey: authStatusKey })
  }
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: rereadHiddenFeatures }),
    mutationCache: new MutationCache({ onError: rereadHiddenFeatures }),
    defaultOptions: {
      queries: {
        staleTime: DEFAULT_STALE_MS,
        refetchOnWindowFocus: false,
        retry: (failures, error) => failures < 1 && (isApiError(error, 'network') || isApiError(error, 'unavailable')),
      },
      mutations: { retry: false },
    },
  })
  return client
}

function viewer(): string {
  const current = session.current()
  return `${session.generation()}:${current.status === 'signedIn' ? current.user.role : ''}`
}

/**
 * Keeps the cache to the viewer it was filled for: when another user holds the tab, the user signs out, the server ends
 * the session or the role changes, the private queries go, and so does every mutation, whose state (a backtest still
 * running, a refusal on screen) is the last viewer's. Returns the function that stops it.
 */
export function scopeCacheToSession(client: QueryClient): () => void {
  let seen = viewer()
  return session.subscribe(() => {
    const now = viewer()
    if (now === seen) return
    seen = now
    client.removeQueries({ queryKey: ['owner'] })
    client.removeQueries({ queryKey: ['admin'] })
    client.getMutationCache().clear()
  })
}
