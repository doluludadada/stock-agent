import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, useSession, type Schemas } from '@/shared/api'

export type SettingsFileId = Schemas['SettingsFile']
export type SettingsFilePage = Schemas['SettingsFileResponse']
export type SettingsEdit = Schemas['SettingsEditResponse']
export type EditableSetting = Schemas['EditableSetting']
export type SettingValue = Schemas['SettingsChangesRequest']['changes'][string]

export const adminKeys = {
  all: ['admin'] as const,
  file: (file: SettingsFileId) => ['admin', 'settings', file] as const,
  backups: (file: SettingsFileId) => ['admin', 'settings', file, 'backups'] as const,
  audit: ['admin', 'audit'] as const,
}

export function useSettingsFile(file: SettingsFileId) {
  const { unlocked } = useSession('admin')
  return useQuery({
    queryKey: adminKeys.file(file),
    queryFn: ({ signal }) => apiRequest('get', '/v1/admin/settings/{file}', { scope: 'admin', params: { file }, signal }),
    enabled: unlocked,
    staleTime: 0,
  })
}

export function useSettingsBackups(file: SettingsFileId) {
  const { unlocked } = useSession('admin')
  return useQuery({
    queryKey: adminKeys.backups(file),
    queryFn: ({ signal }) => apiRequest('get', '/v1/admin/settings/{file}/backups', { scope: 'admin', params: { file }, signal }),
    enabled: unlocked,
  })
}

export function useSettingsAudit() {
  const { unlocked } = useSession('admin')
  return useQuery({ queryKey: adminKeys.audit, queryFn: ({ signal }) => apiRequest('get', '/v1/admin/audit', { scope: 'admin', query: { limit: 20 }, signal }), enabled: unlocked })
}

type Changes = Record<string, SettingValue>

export function usePreviewChange(file: SettingsFileId) {
  return useMutation({
    mutationFn: ({ revision, changes }: { revision: string; changes: Changes }) =>
      apiRequest('post', '/v1/admin/settings/{file}/preview', { scope: 'admin', params: { file }, body: { revision, changes } }),
  })
}

/** Saves with the revision read; 409 and 422 save nothing. Every admin query refetches after, so the page shows the file as it is. */
export function useSaveChange(file: SettingsFileId) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ revision, changes }: { revision: string; changes: Changes }) =>
      apiRequest('put', '/v1/admin/settings/{file}', { scope: 'admin', params: { file }, body: { confirm: true, revision, changes } }),
    onSettled: () => client.invalidateQueries({ queryKey: adminKeys.all }),
  })
}

export function usePreviewRestore(file: SettingsFileId) {
  return useMutation({
    mutationFn: ({ backupId, revision }: { backupId: string; revision: string }) =>
      apiRequest('post', '/v1/admin/settings/{file}/backups/{backup_id}/preview', { scope: 'admin', params: { file, backup_id: backupId }, body: { revision } }),
  })
}

export function useRestore(file: SettingsFileId) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ backupId, revision }: { backupId: string; revision: string }) =>
      apiRequest('post', '/v1/admin/settings/{file}/backups/{backup_id}/restore', {
        scope: 'admin',
        params: { file, backup_id: backupId },
        body: { confirm: true, revision },
      }),
    onSettled: () => client.invalidateQueries({ queryKey: adminKeys.all }),
  })
}
