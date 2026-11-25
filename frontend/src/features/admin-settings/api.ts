import { useQuery } from '@tanstack/react-query'
import { apiRequest, settingsFormKey, useHasPermission } from '@/shared/api'
import type { SettingField } from './form'

/** Every setting the form shows, with its value in the settings files now and what it accepts. */
export function useSettingsForm() {
  return useQuery({
    queryKey: settingsFormKey,
    queryFn: ({ signal }): Promise<SettingField[]> => apiRequest('get', '/v1/admin/settings', { signal }),
    enabled: useHasPermission('edit_system_settings'),
  })
}
