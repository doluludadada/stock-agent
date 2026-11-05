import { isApiError, type ErrorCode, type Schemas } from '@/shared/api'

export type SettingsFileId = Schemas['SettingsFile']
export type SettingsOverview = Schemas['SettingsOverviewResponse']
export type FileStatus = Schemas['SettingsFileStatusResponse']
export type SettingsEdit = Schemas['SettingsEditResponse']
export type SettingsProblem = Schemas['SettingsProblem']
export type SettingsBackup = Schemas['SettingsBackupResponse']
export type AuditEntry = Schemas['SettingsAuditEntryResponse']
export type Refusal = NonNullable<SettingsOverview['refused']>

/** What the server does with one file on disk: runs on it, is loading an edit made there, or refused that edit. */
export type DiskState = { kind: 'running' } | { kind: 'loading' } | { kind: 'refused'; refusal: Refusal }

/**
 * The refusal the server keeps for the files as they are on disk now. A refusal names the revisions it read; once a
 * file changes again the server tries the new files within a poll, so an older refusal says nothing about them.
 */
export function currentRefusal(overview: SettingsOverview): Refusal | null {
  const refused = overview.refused
  return refused && overview.files.every((status) => refused.revisions[status.file] === status.revision) ? refused : null
}

export function diskStateOf(overview: SettingsOverview, status: FileStatus): DiskState {
  if (status.revision === status.running_revision) return { kind: 'running' }
  const refusal = currentRefusal(overview)
  return refusal ? { kind: 'refused', refusal } : { kind: 'loading' }
}

/** True while an edit made on disk waits for the server's next look, so the page asks again sooner. */
export function isLoadingFromDisk(overview: SettingsOverview): boolean {
  return overview.files.some((status) => diskStateOf(overview, status).kind === 'loading')
}

/** A problem the editor can point at: in the open file, at a line and a column, 1-based as the server counts. */
export interface LocatedProblem {
  line: number
  column: number
  message: string
  path: string | null
}

export function locatedIn(problems: readonly SettingsProblem[], file: SettingsFileId): LocatedProblem[] {
  return problems.flatMap((problem) =>
    problem.file === file && problem.line ? [{ line: problem.line, column: problem.column ?? 1, message: problem.message, path: problem.path ?? null }] : [],
  )
}

/** Reading order: the open file's problems by line, then the other file's, then those no file sets (.env, the database). */
export function sortProblems(problems: readonly SettingsProblem[], file: SettingsFileId): SettingsProblem[] {
  const rank = (problem: SettingsProblem) => (problem.file === file ? 0 : problem.file ? 1 : 2)
  return [...problems].sort((a, b) => rank(a) - rank(b) || (a.line ?? 0) - (b.line ?? 0) || (a.column ?? 0) - (b.column ?? 0))
}

/**
 * The parts of a check a reader can trust. A text with a problem may not parse, and then the server lists every
 * setting as changed: only the problems and the line diff say anything, so the changed settings are shown once the
 * problems are gone.
 */
export type Check =
  | { kind: 'checking' }
  | { kind: 'problems'; edit: SettingsEdit }
  | { kind: 'ready'; edit: SettingsEdit }
  | { kind: 'failed'; error: unknown }

export function checkOf(edit: SettingsEdit): Check {
  return edit.problems.length > 0 ? { kind: 'problems', edit } : { kind: 'ready', edit }
}

/** One row of a unified diff, numbered on the side or sides it belongs to. */
export type DiffRow =
  | { kind: 'hunk'; oldStart: number; newStart: number }
  | { kind: 'context' | 'added' | 'removed'; text: string; oldLine: number | null; newLine: number | null }

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/

/** The server's unified diff (Python's difflib, three lines of context) as rows; the two file header lines are dropped. */
export function parseDiff(lines: readonly string[]): DiffRow[] {
  const rows: DiffRow[] = []
  let oldLine = 0
  let newLine = 0
  for (const line of lines) {
    const hunk = HUNK.exec(line)
    if (hunk) {
      oldLine = Number(hunk[1])
      newLine = Number(hunk[2])
      rows.push({ kind: 'hunk', oldStart: oldLine, newStart: newLine })
    } else if (line.startsWith('---') || line.startsWith('+++')) {
      continue
    } else if (line.startsWith('+')) {
      rows.push({ kind: 'added', text: line.slice(1), oldLine: null, newLine: newLine++ })
    } else if (line.startsWith('-')) {
      rows.push({ kind: 'removed', text: line.slice(1), oldLine: oldLine++, newLine: null })
    } else {
      rows.push({ kind: 'context', text: line.slice(1), oldLine: oldLine++, newLine: newLine++ })
    }
  }
  return rows
}

/** The lines of the new text a diff adds or changes, by their 1-based number there. */
export function linesAdded(diff: readonly string[]): number[] {
  return parseDiff(diff).flatMap((row) => (row.kind === 'added' && row.newLine !== null ? [row.newLine] : []))
}

/** A save or a restore from the audit, with the backup of the text it replaced when one is still kept. */
export interface Change {
  entry: AuditEntry
  before: SettingsBackup | null
}

export interface FileHistory {
  changes: Change[]
  /** Kept backups no audit entry in reach names, such as one older than the entries the audit returned. */
  unmatched: SettingsBackup[]
}

/** The longest gap between a save's audit entry and the backup it took: both are written inside one save. */
const SAME_SAVE_MS = 60_000

/**
 * Joins one file's audit entries with its backups: a save backs up the text it replaces, so its backup has the
 * entry's from_revision and was taken within moments of it. Each backup belongs to one save at most.
 */
export function historyOf(file: SettingsFileId, backups: readonly SettingsBackup[], audit: readonly AuditEntry[]): FileHistory {
  const left = [...backups]
  const changes = audit
    .filter((entry) => entry.file === file)
    .map((entry) => {
      const at = Date.parse(entry.recorded_at)
      const candidates = left
        .map((backup, index) => ({ backup, index, gap: Math.abs(Date.parse(backup.created_at) - at) }))
        .filter(({ backup, gap }) => backup.revision === entry.from_revision && gap <= SAME_SAVE_MS)
        .sort((a, b) => a.gap - b.gap)
      const match = candidates[0]
      if (match) left.splice(match.index, 1)
      return { entry, before: match?.backup ?? null }
    })
  return { changes, unmatched: left }
}

/** Why a save or a restore did not happen, in the terms the page answers each one. */
export type SaveRefusal =
  | { kind: 'wrongPassword' }
  | { kind: 'throttled'; retryAfter: number | null }
  | { kind: 'conflict' }
  | { kind: 'refused'; problems: SettingsProblem[]; detail: string }
  | { kind: 'failed'; error: unknown }

/** By the refusal's code, never its words or its status alone: a 403 can be a wrong password, a lost role or a file. */
export function refusalOf(error: unknown): SaveRefusal {
  if (!isApiError(error)) return { kind: 'failed', error }
  switch (error.code) {
    case 'password_refused':
      return { kind: 'wrongPassword' }
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

export function isSettingsFileId(value: unknown): value is SettingsFileId {
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

/** The editor's refusals the page says in its own words, by code. */
const REASONS = {
  administrators_only: 'reason.administratorsOnly',
  password_required: 'reason.passwordRequired',
  settings_file_refused: 'reason.fileRefused',
  settings_file_missing: 'reason.fileMissing',
} as const satisfies Partial<Record<ErrorCode, string>>

function hasReason(code: ErrorCode): code is keyof typeof REASONS {
  return Object.hasOwn(REASONS, code)
}

/** A failed request in the reader's words: the editor's own refusals by code, else the kind of failure or the server's reason. */
export function reasonOf(error: unknown, t: (key: string) => string): string {
  if (!isApiError(error)) return t('common:errors.server')
  if (error.code && hasReason(error.code)) return t(REASONS[error.code])
  return error.kind === 'network' || error.kind === 'server' || error.kind === 'unavailable' ? t(`common:errors.${error.kind}`) : error.message
}
