import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, isApiError, strategyResultsKey, useIsSignedIn } from '@/shared/api'
import type { StrategySettings } from '../model/types'
import { settingsFromApi, settingsToApi, strategyFromApi } from './mapping'

export const strategyKeys = {
  builtIns: ['public', 'technical-settings', 'built-in'] as const,
  settings: ['owner', 'technical-settings'] as const,
}

/** The developer's strategies; they change only with the server's deployment. */
export function useBuiltInStrategies() {
  return useQuery({
    queryKey: strategyKeys.builtIns,
    queryFn: async ({ signal }) => (await apiRequest('get', '/v1/technical-settings/built-in-strategies', { signal })).map(strategyFromApi),
    staleTime: 10 * 60_000,
  })
}

export function useStrategySettings() {
  const signedIn = useIsSignedIn()
  return useQuery({
    queryKey: strategyKeys.settings,
    queryFn: async ({ signal }) => settingsFromApi(await apiRequest('get', '/v1/technical-settings', { signal })),
    enabled: signedIn,
  })
}

/**
 * Saves the whole settings with the revision they carry. A 409 means another tab or device saved first: the cached
 * settings are refetched and the caller keeps its change to reapply, so nobody's save is overwritten silently.
 * Either way the saved strategy may have changed, so every result computed with the old one is dropped.
 */
export function useSaveStrategySettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (settings: StrategySettings) =>
      settingsFromApi(
        await apiRequest('put', '/v1/technical-settings', { body: { confirm: true, settings: settingsToApi(settings) } }),
      ),
    onSuccess: (saved) => {
      client.setQueryData(strategyKeys.settings, saved)
      void client.resetQueries({ queryKey: strategyResultsKey })
    },
    onError: (error) => {
      if (!isApiError(error, 'conflict')) return
      void client.invalidateQueries({ queryKey: strategyKeys.settings })
      void client.resetQueries({ queryKey: strategyResultsKey })
    },
  })
}
