import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { Toaster } from 'sonner'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import { AdminSettingsPage } from './AdminSettingsPage'
import type { SettingField } from './form'

const PASSWORD = 'correct horse battery'

function field(path: string, kind: SettingField['kind'], value: SettingField['value'], extra: Partial<SettingField> = {}): SettingField {
  return { path, kind, value, options: [], minimum: null, maximum: null, exclusive_minimum: null, exclusive_maximum: null, restart_only: false, ...extra }
}

/** One setting of each kind, as GET /v1/admin/settings answers them. */
function fields(): SettingField[] {
  return [
    field('environment', 'choice', 'dev', { options: ['dev', 'test', 'prod'], restart_only: true }),
    field('ai.active_model', 'choice', 'claude', { options: ['openai', 'gemini', 'claude'] }),
    field('ai.available_models', 'structure', { claude: 'claude-haiku-5-5' }),
    field('ai.user_selectable', 'choices', [], { options: ['openai', 'gemini', 'claude'] }),
    field('ai.temperature', 'number', 0.7, { minimum: 0, maximum: 2 }),
    field('behavior.web_search_triggers', 'lines', ['latest', 'news']),
    field('accounts.registration_open', 'switch', true),
  ]
}

/** The settings API in memory: a save needs the password, and a value the app would refuse answers its problem. */
function fakeServer() {
  const state = { fields: fields(), saves: 0 }
  const sent: { method: string; body: Record<string, unknown> | null }[] = []
  const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { 'Content-Type': 'application/json' } })
  const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
    sent.push({ method, body })
    if (String(input) !== '/v1/admin/settings') return json({ detail: 'Not found', code: 'not_found' }, 404)
    if (method === 'GET') return json(state.fields)
    if (body?.password !== PASSWORD) return json({ detail: 'The password is wrong. Nothing was saved.', code: 'password_refused' }, 403)
    const changes = body.changes as { path: string; value: SettingField['value'] }[]
    const selectable = changes.find((change) => change.path === 'ai.user_selectable')
    if (Array.isArray(selectable?.value) && selectable.value.includes('openai')) {
      const problem = { message: 'openai needs OPENAI_API_KEY', path: 'ai.user_selectable.0', code: 'ai_key_missing', params: { provider: 'openai', variable: 'OPENAI_API_KEY' } }
      return json({ detail: 'The app would not start with these settings', code: 'settings_refused', problems: [problem] }, 422)
    }
    state.saves += 1
    state.fields = state.fields.map((item) => ({ ...item, value: changes.find((change) => change.path === item.path)?.value ?? item.value }))
    return json(state.fields)
  })
  return { state, sent, fetch }
}

function renderPage(server: ReturnType<typeof fakeServer>, user = TEST_ADMIN) {
  vi.stubGlobal('fetch', server.fetch)
  const i18n = initI18n('en')
  void i18n.changeLanguage('en')
  session.signIn(user)
  const router = createMemoryRouter(
    [
      { path: '/admin/settings', element: <AdminSettingsPage /> },
      { path: '/elsewhere', element: <p>Another page</p> },
    ],
    { initialEntries: ['/admin/settings'] },
  )
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RouterProvider router={router} />
        <Toaster />
      </QueryClientProvider>
    </I18nextProvider>,
  )
  return router
}

const saveButton = () => screen.getByRole('button', { name: 'Save' })

async function saveWith(user: ReturnType<typeof userEvent.setup>, password = PASSWORD) {
  await user.click(saveButton())
  const dialog = await screen.findByRole('dialog', { name: 'Save the settings?' })
  await user.type(within(dialog).getByLabelText('Your password'), password)
  await user.click(within(dialog).getByRole('button', { name: 'Save and apply' }))
  return dialog
}

describe('the settings page', { timeout: 30_000 }, () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = () => undefined
  })

  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('shows every setting with the control its kind gets, and no YAML', async () => {
    renderPage(fakeServer())

    expect(await screen.findByRole('switch', { name: 'Open registration' })).toBeChecked()
    expect(screen.getByRole('combobox', { name: 'Default AI model' })).toHaveTextContent('Claude')
    const temperature = screen.getByRole('spinbutton', { name: 'Temperature' })
    expect(temperature).toHaveValue(0.7)
    expect(temperature).toHaveAttribute('min', '0')
    expect(temperature).toHaveAttribute('max', '2')
    expect(screen.getByRole('group', { name: 'Models users may pick' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Model id of each provider' })).toHaveValue(JSON.stringify({ claude: 'claude-haiku-5-5' }, null, 2))
    expect(screen.queryByText(/appsetting\.yaml/)).not.toBeInTheDocument()
    expect(saveButton()).toBeDisabled()
  })

  it('shows a setting that changes only at a restart as text, with the reason, and no control', async () => {
    renderPage(fakeServer())

    const row = (await screen.findByText('Development (dev)')).closest('[id="setting-environment"]') as HTMLElement
    expect(within(row).getByText('Changes only when the app restarts.')).toBeInTheDocument()
    expect(within(row).queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('saves only the changed settings with the password, and shows the saved values', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    const temperature = await screen.findByRole('spinbutton', { name: 'Temperature' })
    await user.clear(temperature)
    await user.type(temperature, '0.4')
    await user.click(screen.getByRole('switch', { name: 'Open registration' }))
    await saveWith(user)

    await waitFor(() => expect(server.state.saves).toBe(1))
    const put = server.sent.find((request) => request.method === 'PUT')
    expect(put?.body).toEqual({ confirm: true, password: PASSWORD, changes: [{ path: 'ai.temperature', value: 0.4 }, { path: 'accounts.registration_open', value: false }] })
    expect(await screen.findByText('Saved. The server runs on the new settings now.')).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue(0.4)
    expect(screen.getByRole('switch', { name: 'Open registration' })).not.toBeChecked()
    expect(saveButton()).toBeDisabled()
  })

  it('keeps the dialog open on a wrong password, and saves nothing', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('switch', { name: 'Open registration' }))
    const dialog = await saveWith(user, 'not my password')

    expect(await within(dialog).findByText('The password is wrong. Nothing was saved.')).toBeInTheDocument()
    expect(server.state.saves).toBe(0)
  })

  it('holds a value out of the schema’s bounds at its field, with the refusal’s words, and keeps Save off', async () => {
    renderPage(fakeServer())
    const user = userEvent.setup()

    const temperature = await screen.findByRole('spinbutton', { name: 'Temperature' })
    await user.clear(temperature)
    await user.type(temperature, '5')

    expect(temperature).toHaveAccessibleDescription(/Must be at most 2\./)
    expect(saveButton()).toBeDisabled()
  })

  it('shows each problem of a refused save at its setting, in the reader’s words, until that setting changes', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    const offered = await screen.findByRole('group', { name: 'Models users may pick' })
    await user.click(within(offered).getByRole('checkbox', { name: 'OpenAI' }))
    await saveWith(user)

    const problem = 'openai needs OPENAI_API_KEY in the environment or .env, or the app would not start.'
    expect(await screen.findByText(problem)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(server.state.saves).toBe(0)

    await user.click(within(offered).getByRole('checkbox', { name: 'OpenAI' }))
    expect(screen.queryByText(problem)).not.toBeInTheDocument()
  })

  it('edits a list one item per line, and asks before leaving with a change unsaved', async () => {
    const server = fakeServer()
    const router = renderPage(server)
    const user = userEvent.setup()

    const triggers = await screen.findByRole('textbox', { name: 'Words that start a web search' })
    expect(triggers).toHaveValue('latest\nnews')
    await user.type(triggers, '\ntoday')
    void router.navigate('/elsewhere')

    const leave = await screen.findByRole('alertdialog', { name: 'Leave this page?' })
    await user.click(within(leave).getByRole('button', { name: 'Keep editing' }))
    await user.click(saveButton())
    const dialog = await screen.findByRole('dialog', { name: 'Save the settings?' })
    await user.type(within(dialog).getByLabelText('Your password'), PASSWORD)
    await user.click(within(dialog).getByRole('button', { name: 'Save and apply' }))

    await waitFor(() => expect(server.state.saves).toBe(1))
    expect(server.sent.find((request) => request.method === 'PUT')?.body?.changes).toEqual([{ path: 'behavior.web_search_triggers', value: ['latest', 'news', 'today'] }])
  })

  it('tells a user without the role that the page is for administrators, and asks the server nothing', async () => {
    const server = fakeServer()
    renderPage(server, TEST_USER)

    expect(await screen.findByText('For administrators only')).toBeInTheDocument()
    expect(server.fetch).not.toHaveBeenCalled()
  })
})
