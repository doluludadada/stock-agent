import { isApiError, type ErrorCode, type Schemas } from '@/shared/api'

export type SettingsProblem = Schemas['SettingsProblem']
type SettingsFileId = Schemas['SettingsFile']

type Wording = (key: string, options: Record<string, unknown>) => string

/**
 * What a problem says, in the reader's language: `admin:refusal.<code>` with the server's params for a code this app
 * words, such as pydantic's less_than_equal, else the server's own English.
 */
export function problemMessage(problem: SettingsProblem, t: Wording): string {
  return problem.code ? t(`refusal.${problem.code}`, { ...problem.params, defaultValue: problem.message }) : problem.message
}

/** Why a save did not happen, in the terms the page answers each one. */
export type SaveRefusal =
  | { kind: 'wrongPassword' }
  | { kind: 'googleRequired' }
  | { kind: 'throttled'; retryAfter: number | null }
  | { kind: 'conflict' }
  | { kind: 'refused'; problems: SettingsProblem[]; detail: string }
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
      return { kind: 'refused', problems: problemsOf(error.body), detail: error.message }
    default:
      return { kind: 'failed', error }
  }
}

/** The located problems of a 422 the app would not start with: `{detail, problems}`. Anything else holds none. */
export function problemsOf(body: unknown): SettingsProblem[] {
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

/** The refusals the page says in its own words, by code. */
const REASONS = {
  administrators_only: 'reason.administratorsOnly',
  password_required: 'reason.passwordRequired',
  settings_file_refused: 'reason.fileRefused',
  settings_file_missing: 'reason.fileMissing',
} as const satisfies Partial<Record<ErrorCode, string>>

function hasReason(code: ErrorCode): code is keyof typeof REASONS {
  return Object.hasOwn(REASONS, code)
}

/** A failed request in the reader's words: the page's own refusals by code, else the kind of failure or the server's reason. */
export function reasonOf(error: unknown, t: (key: string) => string): string {
  if (!isApiError(error)) return t('common:errors.server')
  if (error.code && hasReason(error.code)) return t(REASONS[error.code])
  return error.kind === 'network' || error.kind === 'server' || error.kind === 'unavailable' ? t(`common:errors.${error.kind}`) : error.message
}
