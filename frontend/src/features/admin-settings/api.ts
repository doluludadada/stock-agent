import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, isSameSession, sentInSession, useHasPermission } from '@/shared/api'
import type { SettingChange, SettingField } from './form'

const FORM_KEY = ['admin', 'settings', 'form'] as const

/** Every setting the form shows, with its value in the settings files now and what it accepts. */
export function useSettingsForm() {
  return useQuery({
    queryKey: FORM_KEY,
    queryFn: ({ signal }): Promise<SettingField[]> => apiRequest('get', '/v1/admin/settings', { signal }),
    enabled: useHasPermission('edit_system_settings'),
  })
}

/**
 * Writes the changes into the settings files and runs on them at once; the answer is the form after the save. A save
 * can change what any page shows, the ranking's formula for one, so every other answer the tab holds is asked again,
 * after a refusal too: the server writes a turn-off of ordering on its own before it reviews the rest, so a refused
 * save may still have turned ordering off.
 */
export function useSaveSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ changes, ...confirmation }: { changes: SettingChange[] } & ({ password: string } | { google_confirmation: string })) =>
      apiRequest('put', '/v1/admin/settings', { body: { confirm: true, changes, ...confirmation } }),
    onMutate: sentInSession,
    onSuccess: (fields, _, sent) => {
      if (isSameSession(sent)) client.setQueryData(FORM_KEY, fields)
    },
    onSettled: () => {
      void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'admin' })
    },
  })
}
