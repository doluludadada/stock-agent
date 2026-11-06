import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, useHasPermission } from '@/shared/api'
import type { SettingChange, SettingsForm } from './form'
import { isLoadingFromDisk, type SettingsEdit, type SettingsFileId, type SettingsOverview } from './model'

/**
 * The settings files' endpoints. The overview is the one thing polled: it says each file's revision on disk and the
 * one the server runs. A revision's text never changes, so the text is cached by revision and read once.
 */
export const settingsKeys = {
  overview: ['admin', 'settings', 'overview'] as const,
  text: (file: SettingsFileId, revision: string) => ['admin', 'settings', file, 'text', revision] as const,
  check: (file: SettingsFileId, revision: string, text: string) => ['admin', 'settings', file, 'check', revision, text] as const,
  form: (text: string) => ['admin', 'settings', 'appsetting', 'form', text] as const,
  backups: (file: SettingsFileId) => ['admin', 'settings', file, 'backups'] as const,
  restore: (file: SettingsFileId, backupId: string, revision: string) => ['admin', 'settings', file, 'restore', backupId, revision] as const,
  audit: ['admin', 'settings', 'audit'] as const,
}

/** How often the page asks: an edit on disk reaches the server within api.settings_poll_seconds (2 s by default). */
const POLL_MS = 5_000
const POLL_WHILE_LOADING_MS = 1_000
/** The most audit entries the API returns; the history joins them with the backups. */
const AUDIT_LIMIT = 200

function useAllowed() {
  return useHasPermission('edit_system_settings')
}

export function useSettingsOverview() {
  return useQuery({
    queryKey: settingsKeys.overview,
    queryFn: ({ signal }) => apiRequest('get', '/v1/admin/settings', { signal }),
    enabled: useAllowed(),
    refetchInterval: (query) => (query.state.data && isLoadingFromDisk(query.state.data) ? POLL_WHILE_LOADING_MS : POLL_MS),
  })
}

/** A file's whole text and the revision it has: the server's own pair, read in one answer. */
export interface FileText {
  revision: string
  text: string
}

/**
 * The text of the revision on disk. The overview names the revision, so a newer file is read as soon as it is seen;
 * the answer says the revision it really read, which is the one a draft starts from. A file that changed again
 * between the overview and this read answers with its newer revision: that text is kept under its own revision, the
 * overview takes the file's newer status, and the entry asked for stays stale, so it is read again if it comes back.
 */
export function useSettingsText(file: SettingsFileId, revision: string) {
  const client = useQueryClient()
  return useQuery({
    queryKey: settingsKeys.text(file, revision),
    queryFn: async ({ signal }): Promise<FileText> => {
      const document = await apiRequest('get', '/v1/admin/settings/{file}', { params: { file }, signal })
      const read = { revision: document.status.revision, text: document.text }
      if (read.revision !== revision) {
        client.setQueryData(settingsKeys.text(file, read.revision), read)
        client.setQueryData<SettingsOverview>(settingsKeys.overview, (overview) =>
          overview && { ...overview, files: overview.files.map((status) => (status.file === file ? document.status : status)) },
        )
      }
      return read
    },
    enabled: useAllowed(),
    staleTime: (query) => (query.state.data?.revision === revision ? Infinity : 0),
    // While a newer revision loads, the editor keeps showing the one before, never another file's text.
    placeholderData: (previous, query) => (query?.queryKey[2] === file ? previous : undefined),
  })
}

/**
 * What saving `text` over the file at `revision` would do, and its problems, as the server checks a start. Nothing is
 * written. Each text is checked once against its revision; the save is checked again by the server either way.
 */
export function useSettingsCheck(file: SettingsFileId, revision: string, text: string, enabled: boolean) {
  return useQuery({
    queryKey: settingsKeys.check(file, revision, text),
    queryFn: ({ signal }) => apiRequest('post', '/v1/admin/settings/{file}/preview', { params: { file }, body: { revision, text }, signal }),
    enabled: useAllowed() && enabled,
    staleTime: Infinity,
    gcTime: 60_000,
    retry: false,
    placeholderData: keepPreviousData,
  })
}

/** The settings form's reading of a text of appsetting.yaml: the settings it sets and what each accepts. Nothing is written. */
export function useSettingsForm(text: string) {
  return useQuery({
    queryKey: settingsKeys.form(text),
    queryFn: ({ signal }): Promise<SettingsForm> => apiRequest('post', '/v1/admin/settings/appsetting/form', { body: { text, changes: [] }, signal }),
    enabled: useAllowed(),
    staleTime: Infinity,
    gcTime: 60_000,
    retry: false,
    placeholderData: keepPreviousData,
  })
}

/**
 * Writes the form's changes into a text of appsetting.yaml on the server, which answers the new text: the page makes it
 * the draft, so the check and the save treat it as typed. The answer is the form's reading of that text too.
 */
export function useWriteSettingsForm() {
  const client = useQueryClient()
  return async (text: string, changes: SettingChange[]): Promise<SettingsForm> => {
    const form = await apiRequest('post', '/v1/admin/settings/appsetting/form', { body: { text, changes } })
    client.setQueryData(settingsKeys.form(form.text), form)
    return form
  }
}

/** The revisions this tab wrote: when the overview reports one, it is this page's own save, not news from disk. */
const writtenHere = new Set<string>()

export function wasWrittenHere(revision: string): boolean {
  return writtenHere.has(revision)
}

/**
 * After a save or a restore the overview, the backups and the audit are read again. A saved text goes into the cache
 * under its new revision first, so the editor goes on showing it instead of the text before.
 */
function useAfterWrite(file: SettingsFileId) {
  const client = useQueryClient()
  return (edit: SettingsEdit, text: string | null) => {
    writtenHere.add(edit.revision)
    if (text !== null) client.setQueryData<FileText>(settingsKeys.text(file, edit.revision), { revision: edit.revision, text })
    client.setQueryData<SettingsOverview>(settingsKeys.overview, (overview) =>
      overview && {
        ...overview,
        files: overview.files.map((status) => (status.file === file ? { ...status, revision: edit.revision, running_revision: edit.running_revision } : status)),
      },
    )
    void client.invalidateQueries({ queryKey: settingsKeys.overview })
    void client.invalidateQueries({ queryKey: settingsKeys.backups(file) })
    void client.invalidateQueries({ queryKey: settingsKeys.audit })
  }
}

export function useSaveSettings(file: SettingsFileId) {
  const afterWrite = useAfterWrite(file)
  return useMutation({
    mutationFn: ({ revision, text, password }: { revision: string; text: string; password?: string }) =>
      apiRequest('put', '/v1/admin/settings/{file}', { params: { file }, body: { confirm: true, revision, text, password } }),
    onSuccess: (edit, { text }) => afterWrite(edit, text),
  })
}

/** Loads the files on disk again, an edit the server refused before included; the answer is the new overview. */
export function useReloadSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => apiRequest('post', '/v1/admin/settings/reload', { body: { confirm: true } }),
    onSuccess: (overview) => client.setQueryData(settingsKeys.overview, overview),
  })
}

export function useSettingsBackups(file: SettingsFileId) {
  return useQuery({
    queryKey: settingsKeys.backups(file),
    queryFn: ({ signal }) => apiRequest('get', '/v1/admin/settings/{file}/backups', { params: { file }, signal }),
    enabled: useAllowed(),
  })
}

export function useSettingsAudit() {
  return useQuery({
    queryKey: settingsKeys.audit,
    queryFn: ({ signal }) => apiRequest('get', '/v1/admin/audit', { query: { limit: AUDIT_LIMIT }, signal }),
    enabled: useAllowed(),
  })
}

/** What putting a kept backup back would change, checked as a save against the file at `revision`. */
export function useRestorePreview(file: SettingsFileId, backupId: string | null, revision: string) {
  return useQuery({
    queryKey: settingsKeys.restore(file, backupId ?? '', revision),
    queryFn: ({ signal }) =>
      apiRequest('post', '/v1/admin/settings/{file}/backups/{backup_id}/preview', { params: { file, backup_id: backupId ?? '' }, body: { revision }, signal }),
    enabled: useAllowed() && backupId !== null,
    staleTime: Infinity,
    retry: false,
  })
}

export function useRestoreBackup(file: SettingsFileId) {
  const afterWrite = useAfterWrite(file)
  return useMutation({
    mutationFn: ({ backupId, revision, password }: { backupId: string; revision: string; password?: string }) =>
      apiRequest('post', '/v1/admin/settings/{file}/backups/{backup_id}/restore', { params: { file, backup_id: backupId }, body: { confirm: true, revision, password } }),
    onSuccess: (edit) => afterWrite(edit, null),
  })
}
