import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { AdminSettingsPage } from './AdminSettingsPage'
import { drafts } from './drafts'

type FileId = 'appsetting' | 'instructions'
type Problem = { message: string; file: FileId | null; path: string | null; line: number | null; column: number | null }

const PASSWORD = 'correct horse battery'
const APPSETTING = 'environment: dev\nai:\n  temperature: 0.7\ntrading:\n  order_mode: mock_only\n'
/** A text with a setting of each kind the form shows, and a comment the form must keep. */
const FORM_TEXT = [
  'environment: dev',
  'ai:',
  '  # How freely the model words its reply.',
  '  temperature: 0.7',
  '  user_selectable: []',
  'trading:',
  '  order_mode: mock_only',
  'accounts:',
  '  registration_open: true',
  'audience: public',
  '',
].join('\n')

/** The settings classes' schema as the server answers it, cut down to the settings FORM_TEXT sets. */
const SCHEMA = {
  properties: {
    environment: { $ref: '#/$defs/SystemEnvironment', default: 'dev' },
    audience: { $ref: '#/$defs/Audience', default: 'personal' },
    ai: { $ref: '#/$defs/AiConfig' },
    trading: { $ref: '#/$defs/TradingConfig' },
    accounts: { $ref: '#/$defs/AccountsConfig' },
  },
  $defs: {
    SystemEnvironment: { enum: ['dev', 'test', 'prod'], type: 'string', description: 'Which machine the app runs on.' },
    Audience: { enum: ['personal', 'public'], type: 'string', description: 'Whom the deployment serves.' },
    AiProvider: { enum: ['openai', 'gemini', 'claude'], type: 'string' },
    OrderMode: { enum: ['mock_only', 'live', 'disabled'], type: 'string' },
    AiConfig: {
      properties: {
        temperature: { type: 'number', minimum: 0, maximum: 2, description: 'How freely the model words its reply: 0 always picks the likeliest words.' },
        user_selectable: { type: 'array', items: { $ref: '#/$defs/AiProvider' } },
      },
    },
    TradingConfig: { properties: { order_mode: { $ref: '#/$defs/OrderMode', default: 'mock_only' } } },
    AccountsConfig: { properties: { registration_open: { type: 'boolean', description: 'Anyone may register as a user.' } } },
  },
}
const INSTRUCTIONS = 'system_prompt: You are careful.\n'

/** A revision as the server makes one, from the text alone. */
function revisionOf(text: string): string {
  let hash = 7
  for (const char of text) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return hash.toString(16).padStart(8, '0').repeat(8)
}

/** Every setting a text sets, by dotted path, read the way the server's YAML loader would for these small files. */
function leaves(text: string): Map<string, string> {
  const found = new Map<string, string>()
  const parents: string[] = []
  for (const line of text.split('\n')) {
    const match = /^( *)(\w+):\s*(.*)$/.exec(line)
    if (!match) continue
    parents.length = match[1]!.length / 2
    const path = [...parents, match[2]!].join('.')
    if (match[3]) found.set(path, match[3])
    else parents.push(match[2]!)
  }
  return found
}

/** A value of the small texts as the server's YAML loader reads it. */
function typed(raw: string): unknown {
  if (raw === 'true' || raw === 'false') return raw === 'true'
  if (/^-?\d+(\.\d+)?$/.test(raw)) return Number(raw)
  if (raw.startsWith('[')) return raw.slice(1, -1).split(',').map((item) => item.trim()).filter(Boolean)
  return raw
}

/** The text with one setting's value written in place, every other line as it was, as the server's form does. */
function writeSetting(text: string, path: string, value: unknown): string {
  const parents: string[] = []
  return text
    .split('\n')
    .map((line) => {
      const match = /^( *)(\w+):\s*(.*)$/.exec(line)
      if (!match) return line
      parents.length = match[1]!.length / 2
      const at = [...parents, match[2]!].join('.')
      if (!match[3]) parents.push(match[2]!)
      return at === path ? `${match[1]}${match[2]}: ${Array.isArray(value) ? `[${value.join(', ')}]` : String(value)}` : line
    })
    .join('\n')
}

/**
 * The settings API as the backend answers it, kept in memory: whole texts by revision, a check that finds an unclosed
 * list and an order mode the app refuses, saves and restores that need the password, backups, an audit, and a reload
 * that tries the files on disk again. Every refusal carries its code.
 */
function fakeServer() {
  const state = {
    files: { appsetting: APPSETTING, instructions: INSTRUCTIONS } as Record<FileId, string>,
    running: { appsetting: revisionOf(APPSETTING), instructions: revisionOf(INSTRUCTIONS) } as Record<FileId, string>,
    refused: null as null | { revisions: Record<string, string>; previous: Record<string, string>; problems: Problem[]; at: string },
    backups: [] as { backup_id: string; revision: string; created_at: string; file: FileId; text: string }[],
    audit: [] as unknown[],
    wrongPasswords: 0,
    /** Answers the next save with this instead, once. */
    nextSave: null as Response | null,
    /** Holds the audit's answers back until it settles, as a slow network would. */
    auditHeld: null as Promise<void> | null,
    /** Holds the form's answers back the same way. */
    formHeld: null as Promise<void> | null,
    /** Changes appsetting.yaml on disk right before the next read of its text, once. */
    editBeforeRead: null as string | null,
    /** Problems from outside the files, such as a database that is down: every start fails with them while set. */
    outside: null as Problem[] | null,
  }
  const sent: { method: string; url: string; body: Record<string, unknown> | null }[] = []
  const status = (file: FileId) => ({ file, file_name: `${file}.yaml`, revision: revisionOf(state.files[file]), running_revision: state.running[file], modified_at: '2026-11-04T06:00:00Z' })
  const overview = () => ({ environment: 'dev', files: [status('appsetting'), status('instructions')], refused: state.refused, draining: 0 })
  const problemsOf = (file: FileId, text: string): Problem[] =>
    text.split('\n').flatMap((line, index): Problem[] => {
      if (/:\s*\[[^\]]*$/.test(line)) return [{ message: "YAML: expected ',' or ']', but got '<stream end>'", file, path: null, line: index + 1, column: line.indexOf('[') + 1 }]
      if (line.includes('order_mode: sometimes')) return [{ message: "Input should be 'mock_only', 'live' or 'disabled'", file, path: 'trading.order_mode', line: index + 1, column: 3 }]
      if (line.includes('temperature: 5')) return [{ message: 'Input should be less than or equal to 2', file, path: 'ai.temperature', line: index + 1, column: 3 }]
      return []
    })
  const edit = (file: FileId, text: string) => {
    const before = leaves(state.files[file])
    const after = leaves(text)
    const problems = problemsOf(file, text)
    const parsed = !problems.some((problem) => problem.message.startsWith('YAML:'))
    const changed = parsed ? [...new Set([...before.keys(), ...after.keys()])].filter((path) => before.get(path) !== after.get(path)).sort() : []
    const old = state.files[file].split('\n')
    const diff = text.split('\n').flatMap((line, index) => (line === old[index] ? [] : [`@@ -${index + 1},1 +${index + 1},1 @@`, `-${old[index] ?? ''}`, `+${line}`]))
    return {
      file,
      base_revision: revisionOf(state.files[file]),
      revision: revisionOf(text),
      running_revision: state.running[file],
      changed,
      diff: diff.length ? [`--- ${file}.yaml (saved)`, `+++ ${file}.yaml (proposed)`, ...diff] : [],
      problems,
      saved: false,
      applied: false,
    }
  }
  const json = (body: unknown, code = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status: code, headers: { 'Content-Type': 'application/json', ...headers } })
  const write = (file: FileId, text: string, action: 'save' | 'restore', revision: unknown, password: unknown): Response => {
    if (password !== PASSWORD) {
      state.wrongPasswords += 1
      return state.wrongPasswords > 3
        ? json({ detail: 'Too many attempts.', code: 'sign_in_throttled' }, 429, { 'Retry-After': '120' })
        : json({ detail: 'The password is wrong. Nothing was saved.', code: 'password_refused' }, 403)
    }
    if (revision !== revisionOf(state.files[file])) return json({ detail: `${file}.yaml changed since revision; read it again`, code: 'settings_conflict' }, 409)
    const result = edit(file, text)
    if (result.problems.length > 0) return json({ detail: 'The app would not start with these settings', code: 'settings_refused', problems: result.problems }, 422)
    const from = revisionOf(state.files[file])
    state.backups.unshift({ backup_id: `20261104T06000${state.backups.length}Z-0123456789ab`, revision: from, created_at: '2026-11-04T06:00:00Z', file, text: state.files[file] })
    state.audit.unshift({ recorded_at: '2026-11-04T14:00:00+08:00', file, action, actor: 'local', actor_name: 'hsiu', from_revision: from, to_revision: result.revision, settings: result.changed })
    state.files[file] = text
    state.running[file] = result.revision
    return json({ ...result, base_revision: from, running_revision: result.revision, saved: true, applied: true })
  }
  const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
    sent.push({ method, url, body })
    if (url === '/v1/admin/settings') return json(overview())
    if (url === '/v1/admin/settings/reload') {
      const revisions = { appsetting: revisionOf(state.files.appsetting), instructions: revisionOf(state.files.instructions) }
      const problems = state.outside ?? [...problemsOf('appsetting', state.files.appsetting), ...problemsOf('instructions', state.files.instructions)]
      if (problems.length > 0) state.refused = { revisions, previous: { ...state.running }, problems, at: '2026-11-04T06:05:00Z' }
      else {
        state.running = revisions
        state.refused = null
      }
      return json(overview())
    }
    if (url.startsWith('/v1/admin/audit')) {
      await state.auditHeld
      return json(state.audit)
    }
    if (url === '/v1/admin/settings/appsetting/form') {
      await state.formHeld
      const text = String(body?.text)
      const changes = (body?.changes ?? []) as { path: string[]; value: unknown }[]
      const parsed = !problemsOf('appsetting', text).some((problem) => problem.message.startsWith('YAML:'))
      if (!parsed && changes.length > 0) return json({ detail: 'appsetting.yaml does not parse', code: 'settings_edit_refused' }, 422)
      const written = changes.reduce((current, change) => writeSetting(current, change.path.join('.'), change.value), text)
      const values = parsed ? Object.fromEntries([...leaves(written)].map(([path, raw]) => [path, typed(raw)])) : null
      return json({ text: written, values, schema: SCHEMA })
    }
    const [, id, rest] = /^\/v1\/admin\/settings\/(appsetting|instructions)(.*)$/.exec(url) ?? []
    if (id !== 'appsetting' && id !== 'instructions') return json({ detail: 'Not found', code: 'not_found' }, 404)
    if (rest === '' && method === 'GET') {
      if (id === 'appsetting' && state.editBeforeRead !== null) {
        state.files.appsetting = state.editBeforeRead
        state.editBeforeRead = null
      }
      return json({ status: status(id), text: state.files[id] })
    }
    if (rest === '/preview') return body?.revision === revisionOf(state.files[id]) ? json(edit(id, String(body.text))) : json({ detail: 'changed; read it again', code: 'settings_conflict' }, 409)
    if (rest === '' && method === 'PUT') {
      const answer = state.nextSave
      state.nextSave = null
      return answer ?? write(id, String(body?.text), 'save', body?.revision, body?.password)
    }
    if (rest === '/backups') return json(state.backups.filter((backup) => backup.file === id).map(({ backup_id, revision, created_at }) => ({ backup_id, revision, created_at })))
    const restore = /^\/backups\/([^/]+)\/(preview|restore)$/.exec(rest ?? '')
    const backup = state.backups.find((item) => item.backup_id === restore?.[1])
    if (restore && backup && restore[2] === 'preview') return json(edit(id, backup.text))
    if (restore && backup) return write(id, backup.text, 'restore', body?.revision, body?.password)
    return json({ detail: 'No such backup.', code: 'settings_file_missing' }, 404)
  })
  return { state, sent, fetch }
}

function renderPage(server: ReturnType<typeof fakeServer>, user = TEST_ADMIN) {
  vi.stubGlobal('fetch', server.fetch)
  session.signIn(user)
  const router = createMemoryRouter(
    [
      { path: '/admin/settings', element: <AdminSettingsPage /> },
      { path: '/elsewhere', element: <p>Another page</p> },
    ],
    { initialEntries: ['/admin/settings'] },
  )
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </I18nextProvider>,
  )
  return router
}

/** A file's text in the editor. appsetting.yaml opens on its form, so its Advanced (YAML) tab is chosen first. */
async function editor(file = 'appsetting.yaml') {
  if (file === 'appsetting.yaml') {
    const tab = await screen.findByRole('tab', { name: 'Advanced (YAML)' })
    if (tab.getAttribute('aria-selected') !== 'true') await userEvent.click(tab)
  }
  return screen.findByRole('textbox', { name: `The text of ${file}` })
}

const formPanel = () => screen.findByRole('tabpanel', { name: 'Form' })

/** A request of the form that writes a change into the text, not one that only reads a text. */
function writesAChange(request: { url: string; body: Record<string, unknown> | null }): boolean {
  const changes = request.body?.changes
  return request.url === '/v1/admin/settings/appsetting/form' && Array.isArray(changes) && changes.length > 0
}

/** Replaces the whole text the way an administrator pasting a corrected file would. */
async function paste(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.click(await editor())
  await user.keyboard('{Control>}a{/Control}')
  await user.paste(text)
}

const saveButton = () => screen.getByRole('button', { name: 'Save…' })

async function saveWithPassword(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(saveButton()).toBeEnabled())
  await user.click(saveButton())
  const dialog = await screen.findByRole('dialog', { name: 'Save appsetting.yaml?' })
  await user.type(within(dialog).getByLabelText('Your password'), PASSWORD)
  await user.click(within(dialog).getByRole('button', { name: 'Save and apply' }))
}

// Each test drives CodeMirror and a fake server through several checks; on a machine under heavy load that takes
// longer than the default.
describe('the settings editor', { timeout: 90_000 }, () => {
  afterEach(() => {
    drafts.discard('appsetting')
    drafts.discard('instructions')
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('opens appsetting.yaml on its form, offers every file whole in an editor with line numbers, and the prompts only as text', async () => {
    renderPage(fakeServer())
    const user = userEvent.setup()

    expect(await screen.findByRole('tab', { name: 'Form' })).toHaveAttribute('aria-selected', 'true')
    expect(await editor()).toHaveTextContent('order_mode: mock_only')
    expect(screen.getByRole('tab', { name: /appsetting\.yaml/ })).toHaveAttribute('aria-selected', 'true')
    expect(document.querySelector('.cm-lineNumbers')).toHaveTextContent('12345')

    await user.click(screen.getByRole('tab', { name: /instructions\.yaml/ }))

    expect(await editor('instructions.yaml')).toHaveTextContent('system_prompt: You are careful.')
    expect(screen.queryByRole('tab', { name: 'Form' })).not.toBeInTheDocument()
  })

  it('shows each setting with the control its schema gives it, the read-only ones as text, and one the file lacks as left to its default', async () => {
    const server = fakeServer()
    server.state.files.appsetting = FORM_TEXT
    renderPage(server)

    const form = await formPanel()
    expect(await within(form).findByRole('switch', { name: 'Open registration' })).toBeChecked()
    expect(within(form).getByRole('combobox', { name: 'Order mode' })).toHaveTextContent('Mock orders only')
    const temperature = within(form).getByRole('spinbutton', { name: 'Temperature' })
    expect(temperature).toHaveValue(0.7)
    expect(temperature).toHaveAttribute('min', '0')
    expect(temperature).toHaveAttribute('max', '2')
    expect(temperature).toHaveAccessibleDescription(/ai\.temperature.*0 always picks the likeliest words/)
    const offered = within(form).getByRole('group', { name: 'Models users may pick' })
    expect(within(offered).getAllByRole('checkbox').map((box) => box.getAttribute('aria-checked'))).toEqual(['false', 'false', 'false'])
    expect(within(form).getByText('Development (dev)')).toBeInTheDocument()
    expect(within(form).queryByRole('combobox', { name: 'Environment' })).not.toBeInTheDocument()
    expect(within(form).getByText('Public website (public)')).toBeInTheDocument()
    expect(within(form).getByText(/^Read only: the server keeps the audience it started for/)).toBeInTheDocument()
    expect(within(form).queryByRole('combobox', { name: 'Audience' })).not.toBeInTheDocument()
    expect(within(form).getAllByText(/^Not in the file, so the app uses its default\./).length).toBeGreaterThan(0)
  })

  it('makes each change the unsaved text, keeps the comments, checks it, shows it in the YAML, and saves it through the review', async () => {
    const server = fakeServer()
    server.state.files.appsetting = FORM_TEXT
    renderPage(server)
    const user = userEvent.setup()
    const form = await formPanel()
    const registration = await within(form).findByRole('switch', { name: 'Open registration' })

    let answer = () => {}
    server.state.formHeld = new Promise<void>((resolve) => (answer = resolve))
    await user.click(registration)
    await user.click(within(form).getByRole('checkbox', { name: 'Gemini' }))
    answer()
    await waitFor(() => expect(saveButton()).toBeEnabled())

    const written = server.sent.filter(writesAChange)
    expect(written.map((request) => request.body?.changes)).toEqual([[{ path: ['accounts', 'registration_open'], value: false }], [{ path: ['ai', 'user_selectable'], value: ['gemini'] }]])
    expect(written[1]!.body?.text, 'the second change goes into the text the first one made').toContain('registration_open: false')
    const expected = FORM_TEXT.replace('registration_open: true', 'registration_open: false').replace('user_selectable: []', 'user_selectable: [gemini]')
    expect(screen.getByRole('region', { name: 'Check' })).toHaveTextContent('accounts.registration_open')
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()

    const text = await editor()
    expect(text).toHaveTextContent('registration_open: false')
    expect(text).toHaveTextContent('# How freely the model words its reply.')
    await saveWithPassword(user)

    expect(await screen.findByText(/^Saved at .*The server runs on it now\.$/)).toBeInTheDocument()
    expect(server.state.files.appsetting).toBe(expected)
  })

  it('writes a number once the field is left, and shows the problem the check finds next to the setting', async () => {
    const server = fakeServer()
    server.state.files.appsetting = FORM_TEXT
    renderPage(server)
    const user = userEvent.setup()
    const form = await formPanel()

    const temperature = await within(form).findByRole('spinbutton', { name: 'Temperature' })
    await user.clear(temperature)
    await user.type(temperature, '5')
    expect(server.sent.some(writesAChange), 'nothing is written while typing').toBe(false)
    await user.tab()

    expect(await within(form).findByText('Input should be less than or equal to 2')).toBeInTheDocument()
    expect(within(form).getByRole('spinbutton', { name: 'Temperature' })).toHaveAttribute('aria-invalid', 'true')
    expect(saveButton()).toBeDisabled()

    await user.click(within(screen.getByRole('region', { name: 'Check' })).getByRole('button', { name: /^Line 4, column 3/ }))
    expect(screen.getByRole('tab', { name: 'Advanced (YAML)' }), 'a problem’s place opens the text').toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(document.querySelector('.cm-activeLine')).toHaveTextContent('temperature: 5'))
  })

  it('says the form cannot read a text that does not parse, and points to the YAML', async () => {
    renderPage(fakeServer())
    const user = userEvent.setup()

    await paste(user, APPSETTING.replace('order_mode: mock_only', 'order_mode: [mock_only'))
    await user.click(screen.getByRole('tab', { name: 'Form' }))
    expect(await screen.findByText('The form cannot read this text')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Open the text' }))

    expect(screen.getByRole('tab', { name: 'Advanced (YAML)' })).toHaveAttribute('aria-selected', 'true')
    expect(await editor()).toHaveTextContent('order_mode: [mock_only')
  })

  it('shows each problem at its line and column, puts the caret there, and saves nothing while one is left', async () => {
    renderPage(fakeServer())
    const user = userEvent.setup()

    await paste(user, APPSETTING.replace('order_mode: mock_only', 'order_mode: [mock_only'))
    const problem = await screen.findByRole('button', { name: /Line 5, column 15.*YAML: expected/ })
    expect(saveButton()).toBeDisabled()
    await user.click(problem)

    expect(document.querySelector('.cm-activeLine')).toHaveTextContent('order_mode: [mock_only')
    expect(document.querySelector('.cm-lintRange-error')).toHaveTextContent('[mock_only')
  })

  it('asks for the password at every save, keeps the text after a wrong one, and says what the save did', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()
    const text = APPSETTING.replace('temperature: 0.7', 'temperature: 0.4')

    await paste(user, text)
    await waitFor(() => expect(saveButton()).toBeEnabled())
    expect(screen.getByText('ai.temperature')).toBeInTheDocument()
    expect(document.querySelector('.cm-lineNumbers .cm-changedLine')).toHaveTextContent(/^3$/)
    await user.click(saveButton())
    const dialog = await screen.findByRole('dialog', { name: 'Save appsetting.yaml?' })
    expect(within(dialog).getByRole('button', { name: 'Save and apply' })).toBeDisabled()

    await user.type(within(dialog).getByLabelText('Your password'), 'not it')
    await user.click(within(dialog).getByRole('button', { name: 'Save and apply' }))
    expect(await within(dialog).findByText('The password is wrong. Nothing was saved.')).toBeInTheDocument()
    expect(session.current().status).toBe('signedIn')
    expect(server.state.files.appsetting).toBe(APPSETTING)

    await user.type(within(dialog).getByLabelText('Your password'), PASSWORD)
    await user.click(within(dialog).getByRole('button', { name: 'Save and apply' }))

    expect(await screen.findByText(/^Saved at .*The server runs on it now\.$/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(server.state.files.appsetting).toBe(text)
    expect(server.sent.filter((request) => request.method === 'PUT').at(-1)?.body).toEqual({ confirm: true, revision: revisionOf(APPSETTING), text, password: PASSWORD })
    expect(await editor()).toHaveTextContent('temperature: 0.4')
  })

  it('says how long to wait after too many wrong passwords, and keeps the save off until then', async () => {
    const server = fakeServer()
    server.state.wrongPasswords = 3
    renderPage(server)
    const user = userEvent.setup()

    await paste(user, APPSETTING.replace('temperature: 0.7', 'temperature: 0.5'))
    await waitFor(() => expect(saveButton()).toBeEnabled())
    await user.click(saveButton())
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Your password'), 'guess')
    await user.click(within(dialog).getByRole('button', { name: 'Save and apply' }))

    expect(await within(dialog).findByText(/^Too many wrong passwords\. Try again in (2 min 0|1 min 5\d) s\.$/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Save and apply' })).toBeDisabled()
    expect(within(dialog).getByLabelText('Your password')).toBeDisabled()
  })

  it('keeps the text when the app would not start with it, and lists each problem, placed or not', async () => {
    const server = fakeServer()
    const text = APPSETTING.replace('temperature: 0.7', 'temperature: 0.3')
    const unplaced = { message: 'The app would not start: OperationalError. The server log has the details.', file: null, path: null, line: null, column: null }
    server.state.nextSave = new Response(JSON.stringify({ detail: 'The app would not start with these settings', code: 'settings_refused', problems: [unplaced] }), {
      status: 422,
      headers: { 'Content-Type': 'application/json' },
    })
    renderPage(server)
    const user = userEvent.setup()

    await paste(user, text)
    await saveWithPassword(user)

    expect(await screen.findByText('Not saved: the app would not start with this text.')).toBeInTheDocument()
    expect(screen.getByText(unplaced.message)).toBeInTheDocument()
    expect(screen.getByText('Not in a settings file')).toBeInTheDocument()
    expect(await editor()).toHaveTextContent('temperature: 0.3')
    expect(server.state.files.appsetting).toBe(APPSETTING)
  })

  it('keeps the text when the file changed on disk, and saves it over the newer file once the administrator keeps it', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()
    const mine = APPSETTING.replace('temperature: 0.7', 'temperature: 0.2')

    await user.click(await editor())
    server.state.files.appsetting = APPSETTING.replace('environment: dev', 'environment: dev\n# edited on the server')
    await paste(user, mine)

    expect(await screen.findByText('appsetting.yaml changed on disk after you started editing')).toBeInTheDocument()
    expect(await editor()).toHaveTextContent('temperature: 0.2')
    expect(saveButton()).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Keep my text' }))
    await saveWithPassword(user)

    await waitFor(() => expect(server.state.files.appsetting).toBe(mine))
  })

  it('loads the newer file on disk instead, once the administrator chooses to', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    await user.click(await editor())
    server.state.files.appsetting = APPSETTING.replace('environment: dev', 'environment: dev\n# edited on the server')
    await paste(user, APPSETTING.replace('temperature: 0.7', 'temperature: 0.2'))
    await user.click(await screen.findByRole('button', { name: 'Load the file on disk' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Load the file on disk' }))

    await waitFor(async () => expect(await editor()).toHaveTextContent('# edited on the server'))
    expect(await editor()).toHaveTextContent('temperature: 0.7')
  })

  it('asks before leaving with unsaved text, and the text is still there', async () => {
    const router = renderPage(fakeServer())
    const user = userEvent.setup()

    await paste(user, APPSETTING.replace('temperature: 0.7', 'temperature: 0.9'))
    await act(() => router.navigate('/elsewhere'))
    const ask = await screen.findByRole('alertdialog', { name: 'Leave this page?' })
    expect(ask).toHaveTextContent('Your unsaved changes to appsetting.yaml stay in this tab until you save or discard them.')
    await user.click(within(ask).getByRole('button', { name: 'Keep editing' }))

    expect(router.state.location.pathname).toBe('/admin/settings')
    expect(await editor()).toHaveTextContent('temperature: 0.9')
  })

  it('brings back unsaved text typed before the page reloaded, and says so', async () => {
    drafts.put('appsetting', {
      owner: TEST_ADMIN.user_id,
      base: { revision: revisionOf(APPSETTING), text: APPSETTING },
      text: APPSETTING.replace('order_mode: mock_only', 'order_mode: disabled'),
      editedAt: '2026-11-04T05:00:00Z',
    })
    renderPage(fakeServer())

    expect(await editor()).toHaveTextContent('order_mode: disabled')
    expect(screen.getByText(/^Your unsaved changes from .* are still here\.$/)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /appsetting\.yaml.*unsaved changes/ })).toBeInTheDocument()
  })

  it('says an edit on disk was not loaded and why, and loads it when tried again once the cause is gone', async () => {
    const server = fakeServer()
    const edited = APPSETTING.replace('temperature: 0.7', 'temperature: 0.2')
    const databaseDown = { message: 'The app would not start: OperationalError. The server log has the details.', file: null, path: null, line: null, column: null }
    server.state.files.appsetting = edited
    server.state.outside = [databaseDown]
    server.state.refused = {
      revisions: { appsetting: revisionOf(edited), instructions: revisionOf(INSTRUCTIONS) },
      previous: { appsetting: revisionOf(APPSETTING), instructions: revisionOf(INSTRUCTIONS) },
      problems: [databaseDown],
      at: '2026-11-04T06:01:00Z',
    }
    renderPage(server)
    const user = userEvent.setup()

    const banner = await screen.findByRole('alert', { name: 'An edit made on disk was not loaded' })
    expect(within(banner).getByText(databaseDown.message)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /appsetting\.yaml.*the edit on disk was not loaded/ })).toBeInTheDocument()

    server.state.outside = null
    await user.click(within(banner).getByRole('button', { name: 'Try again' }))

    await waitFor(() => expect(screen.queryByRole('alert', { name: 'An edit made on disk was not loaded' })).not.toBeInTheDocument())
    expect(screen.queryByRole('tab', { name: /the edit on disk was not loaded/ })).not.toBeInTheDocument()
    expect(server.state.running.appsetting).toBe(revisionOf(edited))
    expect(server.sent.find((request) => request.url === '/v1/admin/settings/reload')?.body).toEqual({ confirm: true })
  })

  it('says when a try again was refused once more, with the problems the server found then', async () => {
    const server = fakeServer()
    const refusedText = APPSETTING.replace('order_mode: mock_only', 'order_mode: sometimes')
    server.state.files.appsetting = refusedText
    server.state.refused = {
      revisions: { appsetting: revisionOf(refusedText), instructions: revisionOf(INSTRUCTIONS) },
      previous: { appsetting: revisionOf(APPSETTING), instructions: revisionOf(INSTRUCTIONS) },
      problems: [{ message: "Input should be 'mock_only', 'live' or 'disabled'", file: 'appsetting', path: 'trading.order_mode', line: 5, column: 3 }],
      at: '2026-11-04T06:01:00Z',
    }
    renderPage(server)
    const user = userEvent.setup()

    const banner = await screen.findByRole('alert', { name: 'An edit made on disk was not loaded' })
    expect(within(banner).queryByText(/^Still not loaded at /)).not.toBeInTheDocument()

    await user.click(within(banner).getByRole('button', { name: 'Try again' }))

    expect(await within(banner).findByText(/^Still not loaded at .+\.$/)).toBeInTheDocument()
    expect(within(banner).getByRole('button', { name: /Line 5, column 3.*trading\.order_mode/ })).toBeInTheDocument()
    expect(server.state.refused?.at).toBe('2026-11-04T06:05:00Z')
  })

  it('shows who changed the file and when, and restores the version before a change with the password', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    await paste(user, APPSETTING.replace('temperature: 0.7', 'temperature: 0.1'))
    await saveWithPassword(user)
    const history = await screen.findByRole('region', { name: 'History' })
    expect(await within(history).findByText('You saved')).toBeInTheDocument()
    expect(within(history).getByText('ai.temperature')).toBeInTheDocument()
    expect(within(history).getByText('On disk now')).toBeInTheDocument()

    await user.click(within(history).getByRole('button', { name: 'View the version before' }))
    const dialog = await screen.findByRole('dialog', { name: /^Restore the version from before / })
    expect(await within(dialog).findByText('ai.temperature')).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Your password'), PASSWORD)
    await user.click(within(dialog).getByRole('button', { name: 'Restore and apply' }))

    await waitFor(() => expect(server.state.files.appsetting).toBe(APPSETTING))
    expect(await screen.findByText(/^Restored the version from before .* The server runs on it now\.$/)).toBeInTheDocument()
    expect(server.state.files.appsetting).toBe(APPSETTING)
  })

  it('holds the history’s restore buttons until it has read the save just made, so the version before is the right one', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()
    await paste(user, APPSETTING.replace('temperature: 0.7', 'temperature: 0.1'))
    await saveWithPassword(user)
    const history = await screen.findByRole('region', { name: 'History' })
    await within(history).findByText('You saved')

    let answer = () => {}
    server.state.auditHeld = new Promise<void>((resolve) => (answer = resolve))
    await paste(user, APPSETTING.replace('temperature: 0.7', 'temperature: 0.2'))
    await saveWithPassword(user)
    await screen.findByText(/^Saved at /)

    expect(within(history).getAllByRole('button', { name: 'View the version before' })).toHaveLength(1)
    expect(within(history).getByRole('button', { name: 'View the version before' })).toBeDisabled()
    answer()
    await waitFor(() => expect(within(history).getAllByRole('button', { name: 'View the version before' })).toHaveLength(2))
    expect(within(history).getAllByRole('button', { name: 'View the version before' })[0]).toBeEnabled()
  })

  it('shows a file that changed between the overview and the read of its text under the revision it really has', async () => {
    const server = fakeServer()
    const newer = APPSETTING.replace('environment: dev', 'environment: dev\n# edited on the server')
    server.state.editBeforeRead = newer
    renderPage(server)

    expect(await editor()).toHaveTextContent('# edited on the server')
    expect(screen.getByText(new RegExp(`^Revision ${revisionOf(newer).slice(0, 7)} `)), 'at once, not at the next look').toBeInTheDocument()
    expect(screen.getByText('Loading the edit made on disk…')).toBeInTheDocument()
  })

  it('tells a signed-in user without the permission that the page is for administrators, and asks the server for nothing', async () => {
    const server = fakeServer()
    renderPage(server, TEST_USER)

    expect(await screen.findByText('For administrators only')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(server.sent.filter((request) => request.url.startsWith('/v1/admin'))).toEqual([])
  })
})
