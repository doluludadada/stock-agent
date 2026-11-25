import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiRequest, isApiError, type ErrorCode } from './http'
import type { components } from './schema.gen'
import { isSameSession, sentInSession } from './session'

type Schemas = components['schemas']
export type SettingsProblem = Schemas['SettingsProblem']
type SettingsFileId = Schemas['SettingsFile']

/** Every setting the settings page's form shows; a save answers it again. */
export const settingsFormKey = ['admin', 'settings', 'form'] as const

/**
 * Writes the changes into the settings files and runs on them at once; the answer is the form after the save. A save
 * can change what any page shows, the ranking's formula for one, so every other answer the tab holds is asked again,
 * after a refusal too: the server writes a turn-off of ordering on its own before it reviews the rest, so a refused
 * save may still have turned ordering off.
 */
export function useSaveSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ changes, ...confirmation }: { changes: Schemas['SettingChange'][] } & ({ password: string } | { google_confirmation: string })) =>
      apiRequest('put', '/v1/admin/settings', { body: { confirm: true, changes, ...confirmation } }),
    onMutate: sentInSession,
    onSuccess: (fields, _, sent) => {
      if (isSameSession(sent)) client.setQueryData(settingsFormKey, fields)
    },
    onSettled: () => {
      void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'admin' })
    },
  })
}

/** A refusal of the settings themselves, or another save first: the dialog closes, and the page says it. */
export type PageRefusal = { kind: 'refused'; problems: SettingsProblem[]; error: unknown } | { kind: 'conflict' }

/** Why a save did not happen, in the terms the page answers each one. */
export type SaveRefusal =
  | { kind: 'wrongPassword' }
  | { kind: 'googleRequired' }
  | { kind: 'throttled'; retryAfter: number | null }
  | PageRefusal
  | { kind: 'failed'; error: unknown }

/** By the refusal's code, never its words or its status alone: a 403 can be a wrong password or a lost role. */
export function refusalOf(error: unknown): SaveRefusal {
  if (!isApiError(error)) return { kind: 'failed', error }
  switch (error.code) {
    case 'password_refused':
      return { kind: 'wrongPassword' }
    case 'google_confirmation_required':
      return { kind: 'googleRequired' }
    case 'sign_in_throttled':
      return { kind: 'throttled', retryAfter: error.retryAfter }
    case 'settings_conflict':
      return { kind: 'conflict' }
    case 'settings_refused':
    case 'settings_edit_refused':
      return { kind: 'refused', problems: problemsOf(error.body), error }
    default:
      return { kind: 'failed', error }
  }
}

/** The located problems of a 422 the app would not start with: `{detail, problems}`. Anything else holds none. */
function problemsOf(body: unknown): SettingsProblem[] {
  const listed = typeof body === 'object' && body !== null && 'problems' in body ? body.problems : null
  return Array.isArray(listed) ? listed.filter(isSettingsProblem) : []
}

/** Every settings file id once: the compiler refuses this table when the contract adds or drops a file. */
const FILE_IDS = { appsetting: true, instructions: true } as const satisfies Record<SettingsFileId, true>

function isSettingsFileId(value: unknown): value is SettingsFileId {
  return typeof value === 'string' && Object.hasOwn(FILE_IDS, value)
}

function isSettingsProblem(value: unknown): value is SettingsProblem {
  if (typeof value !== 'object' || value === null) return false
  const field = (key: string): unknown => Reflect.get(value, key)
  const optional = (key: string, check: (item: unknown) => boolean) => field(key) === undefined || field(key) === null || check(field(key))
  return (
    typeof field('message') === 'string' &&
    optional('file', isSettingsFileId) &&
    optional('path', (item) => typeof item === 'string') &&
    optional('line', Number.isInteger) &&
    optional('column', Number.isInteger)
  )
}

/** The refusals a save says in its own words, by code. */
const REASONS = {
  administrators_only: 'common:settingsSave.reason.administratorsOnly',
  password_required: 'common:settingsSave.reason.passwordRequired',
  settings_file_refused: 'common:settingsSave.reason.fileRefused',
  settings_file_missing: 'common:settingsSave.reason.fileMissing',
} as const satisfies Partial<Record<ErrorCode, string>>

function hasReason(code: ErrorCode): code is keyof typeof REASONS {
  return Object.hasOwn(REASONS, code)
}

/** A failed save in the reader's words: a save's own refusals by code, else what every page says (`useErrorReason`). */
export function reasonOf(error: unknown, t: (key: string) => string, reason: (error: unknown) => string): string {
  return isApiError(error) && error.code && hasReason(error.code) ? t(REASONS[error.code]) : reason(error)
}
