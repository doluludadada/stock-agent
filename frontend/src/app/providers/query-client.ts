import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { authStatusKey, isApiError } from '@/shared/api'

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
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (failures, error) => failures < 1 && (isApiError(error, 'network') || isApiError(error, 'unavailable')),
      },
      mutations: { retry: false },
    },
  })
  return client
}
