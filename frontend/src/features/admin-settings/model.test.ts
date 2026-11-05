import { ApiError } from '@/shared/api'
import { currentRefusal, diskStateOf, historyOf, isLoadingFromDisk, parseDiff, problemsOf, reasonOf, refusalOf, sortProblems, type AuditEntry, type SettingsBackup, type SettingsOverview } from './model'

const rev = (letter: string) => letter.repeat(64)
const overview = (files: [string, string][], refused: SettingsOverview['refused'] = null): SettingsOverview => ({
  environment: 'dev',
  files: [
    { file: 'appsetting', file_name: 'appsetting.yaml', revision: files[0]![0], running_revision: files[0]![1], modified_at: '2026-11-04T06:00:00Z' },
    { file: 'instructions', file_name: 'instructions.yaml', revision: files[1]![0], running_revision: files[1]![1], modified_at: '2026-11-04T06:00:00Z' },
  ],
  refused,
  draining: 0,
})
const problem = { message: "Input should be 'mock_only', 'live' or 'disabled'", file: 'appsetting' as const, path: 'trading.order_mode', line: 208, column: 3 }

describe('what the server does with the files on disk', () => {
  it('runs a file whose revision on disk is the one it runs, and loads one that changed until its look comes', () => {
    const state = overview([
      [rev('b'), rev('a')],
      [rev('c'), rev('c')],
    ])

    expect(diskStateOf(state, state.files[0]!)).toEqual({ kind: 'loading' })
    expect(diskStateOf(state, state.files[1]!)).toEqual({ kind: 'running' })
    expect(isLoadingFromDisk(state)).toBe(true)
  })

  it('reports a refusal for the files it read, and treats one older than the files on disk as not yet tried', () => {
    const refused = { revisions: { appsetting: rev('b'), instructions: rev('c') }, previous: { appsetting: rev('a'), instructions: rev('c') }, problems: [problem], at: '2026-11-04T06:01:00Z' }
    const now = overview([[rev('b'), rev('a')], [rev('c'), rev('c')]], refused)
    const changedAgain = overview([[rev('d'), rev('a')], [rev('c'), rev('c')]], refused)

    expect(currentRefusal(now)).toBe(refused)
    expect(diskStateOf(now, now.files[0]!)).toEqual({ kind: 'refused', refusal: refused })
    expect(currentRefusal(changedAgain)).toBeNull()
    expect(diskStateOf(changedAgain, changedAgain.files[0]!)).toEqual({ kind: 'loading' })
  })
})

describe('the server’s line diff', () => {
  it('numbers each line on the side it belongs to, from each hunk’s start', () => {
    const rows = parseDiff([
      '--- appsetting.yaml (saved)',
      '+++ appsetting.yaml (proposed)',
      '@@ -205,4 +205,4 @@',
      ' trading:',
      '   execution_provider: mock',
      '-  order_mode: mock_only',
      '+  order_mode: disabled',
      ' ',
    ])

    expect(rows).toEqual([
      { kind: 'hunk', oldStart: 205, newStart: 205 },
      { kind: 'context', text: 'trading:', oldLine: 205, newLine: 205 },
      { kind: 'context', text: '  execution_provider: mock', oldLine: 206, newLine: 206 },
      { kind: 'removed', text: '  order_mode: mock_only', oldLine: 207, newLine: null },
      { kind: 'added', text: '  order_mode: disabled', oldLine: null, newLine: 207 },
      { kind: 'context', text: '', oldLine: 208, newLine: 208 },
    ])
  })
})

describe('a file’s history', () => {
  const backup = (id: string, revision: string, createdAt: string): SettingsBackup => ({ backup_id: id, revision, created_at: createdAt })
  const entry = (from: string, to: string, recordedAt: string, file: AuditEntry['file'] = 'appsetting'): AuditEntry => ({
    recorded_at: recordedAt,
    file,
    action: 'save',
    actor: 'local',
    actor_name: 'hsiu',
    from_revision: from,
    to_revision: to,
    settings: ['ai.temperature'],
  })

  it('gives each save the backup it took of the text it replaced, and lists backups no entry names', () => {
    const later = entry(rev('b'), rev('a'), '2026-11-04T14:05:00.100+08:00')
    const earlier = entry(rev('a'), rev('b'), '2026-11-04T14:00:00.100+08:00')
    const other = entry(rev('x'), rev('y'), '2026-11-04T14:03:00+08:00', 'instructions')
    const backups = [backup('2', rev('b'), '2026-11-04T06:05:00Z'), backup('1', rev('a'), '2026-11-04T06:00:00Z'), backup('0', rev('a'), '2026-11-03T01:00:00Z')]

    const history = historyOf('appsetting', backups, [later, other, earlier])

    expect(history.changes).toEqual([
      { entry: later, before: backups[0] },
      { entry: earlier, before: backups[1] },
    ])
    expect(history.unmatched).toEqual([backups[2]])
  })

  it('says a save’s backup is gone when none of its revision was taken at that time', () => {
    const history = historyOf('appsetting', [backup('9', rev('b'), '2026-11-01T00:00:00Z')], [entry(rev('b'), rev('c'), '2026-11-04T14:00:00+08:00')])

    expect(history.changes[0]!.before).toBeNull()
    expect(history.unmatched).toHaveLength(1)
  })
})

describe('problems', () => {
  it('reads the located problems of a refusal as the server sent them, file included, and drops anything else', () => {
    const elsewhere = { message: 'Field required', file: 'instructions', path: 'prompts.valuation_explanation', line: null, column: null }

    expect(problemsOf({ detail: 'The app would not start', problems: [problem, elsewhere, { line: 3 }, 'text'] })).toEqual([problem, elsewhere])
    expect(problemsOf({ detail: 'appsetting.yaml would be larger than 262144 bytes' })).toEqual([])
    expect(problemsOf(null)).toEqual([])
  })

  it('puts the open file’s problems first by line, then the other file’s, then those no file sets', () => {
    const unplaced = { message: 'The app would not start: OperationalError.', file: null, path: null, line: null, column: null }
    const other = { ...problem, file: 'instructions' as const, line: 2 }
    const early = { ...problem, line: 13 }

    expect(sortProblems([unplaced, other, problem, early], 'appsetting')).toEqual([early, problem, other, unplaced])
  })
})

describe('why a save did not go through', () => {
  const refusal = (kind: ConstructorParameters<typeof ApiError>[0], status: number, body: object, retryAfter: number | null = null) =>
    new ApiError(kind, status, 'detail' in body ? String(body.detail) : '', [], retryAfter, body)

  it('reads each refusal by its code, the way the page answers it', () => {
    expect(refusalOf(refusal('forbidden', 403, { detail: 'The password is wrong. Nothing was saved.', code: 'password_refused' }))).toEqual({ kind: 'wrongPassword' })
    expect(refusalOf(refusal('rateLimited', 429, { detail: 'Too many attempts.', code: 'sign_in_throttled' }, 240))).toEqual({ kind: 'throttled', retryAfter: 240 })
    expect(refusalOf(refusal('conflict', 409, { detail: 'appsetting.yaml changed; read it again', code: 'settings_conflict' }))).toEqual({ kind: 'conflict' })
    expect(refusalOf(refusal('invalid', 422, { detail: 'The app would not start with these settings', code: 'settings_refused', problems: [problem] }))).toEqual({
      kind: 'refused',
      problems: [problem],
      detail: 'The app would not start with these settings',
    })
    expect(refusalOf(refusal('invalid', 422, { detail: 'The new appsetting.yaml would be larger than 1048576 bytes', code: 'settings_edit_refused' }))).toEqual({
      kind: 'refused',
      problems: [],
      detail: 'The new appsetting.yaml would be larger than 1048576 bytes',
    })
    const offline = new ApiError('network', 0, 'Failed to fetch')
    expect(refusalOf(offline)).toEqual({ kind: 'failed', error: offline })
  })

  it('never takes another 403 for a wrong password, and says the editor’s own refusals in its words', () => {
    const t = (key: string) => `t:${key}`
    const lostRole = refusal('forbidden', 403, { detail: 'Only administrators can do this.', code: 'administrators_only' })
    const linkedFile = refusal('forbidden', 403, { detail: 'appsetting.yaml is a symlink', code: 'settings_file_refused' })
    const noCode = refusal('forbidden', 403, { detail: 'Forbidden' })

    for (const error of [lostRole, linkedFile, noCode]) expect(refusalOf(error)).toEqual({ kind: 'failed', error })
    expect(reasonOf(lostRole, t)).toBe('t:reason.administratorsOnly')
    expect(reasonOf(linkedFile, t)).toBe('t:reason.fileRefused')
    expect(reasonOf(noCode, t)).toBe('Forbidden')
  })
})
