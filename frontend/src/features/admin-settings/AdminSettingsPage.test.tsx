import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

function field(path: string, kind: SettingField['kind'], group: SettingField['group'], value: SettingField['value'], extra: Partial<SettingField> = {}): SettingField {
  return { path, kind, group, value, options: [], steps: [], minimum: null, maximum: null, step: null, unit: null, nullable: false, restart_only: false, ...extra }
}

/** One setting of each kind, as GET /v1/admin/settings answers them, in YAML order. */
function fields(): SettingField[] {
  return [
    field('environment', 'choice', 'site_access', 'dev', { options: ['dev', 'test', 'prod'], restart_only: true }),
    field('ai.active_model', 'choice', 'ai', 'claude', { options: ['openai', 'grok', 'gemini', 'groq', 'claude'] }),
    field('ai.available_models', 'structure', 'advanced', { claude: 'claude-haiku-5-5' }),
    field('ai.user_selectable', 'choices', 'ai', [], { options: ['openai', 'gemini', 'claude'] }),
    field('ai.temperature', 'range', 'ai', 0.7, { minimum: 0, maximum: 2, step: 0.1 }),
    field('accounts.google_allowed_emails', 'lines', 'advanced', ['latest', 'news']),
    field('analysis.stop_loss_pct', 'steps', 'trading_limits', 0.07, { steps: [0.05, 0.08, 0.1], unit: 'percent' }),
    field('technical.initial_strategy_id', 'choice', 'trading_limits', 'balanced', { options: ['balanced', 'momentum'] }),
    field('ranking.decision_day', 'range', 'ranking', 10, { minimum: 1, step: 1 }),
    field('ranking.active_formula', 'choice', 'ranking', 'revenue_and_high', { options: ['revenue_and_high', 'revenue_and_high_cash_60'] }),
    field('ranking.follow_times', 'choices', 'ranking', ['09:05:00'], { options: ['09:05:00', '09:30:00'] }),
    field('market.bond_etf_tax_exempt_until', 'date', 'trading_limits', '2026-12-31'),
    field('mock_trading.max_fill_quantity', 'steps', 'trading_limits', null, { steps: [1000, 5000], nullable: true }),
    field('accounts.registration_open', 'switch', 'site_access', true),
    field('accounts.sign_in_window_minutes', 'steps', 'site_access', 15, { steps: [5, 15, 60], unit: 'minutes' }),
    field('features.watchlist', 'choice', 'features', 'everyone', { options: ['off', 'administrators', 'everyone'] }),
  ]
}

/** The settings API in memory: a save needs the password, and a value the app would refuse answers its problem. */
function fakeServer() {
  const state = { fields: fields(), saves: 0, down: false }
  const sent: { method: string; body: Record<string, unknown> | null }[] = []
  const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { 'Content-Type': 'application/json' } })
  const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
    sent.push({ method, body })
    if (String(input) !== '/v1/admin/settings') return json({ detail: 'Not found', code: 'not_found' }, 404)
    if (method === 'GET') return state.down ? json({ detail: 'Internal Server Error' }, 500) : json(state.fields)
    if (body?.password !== PASSWORD) return json({ detail: 'The password is wrong. Nothing was saved.', code: 'password_refused' }, 403)
    const changes = body.changes as { path: string; value: SettingField['value'] }[]
    const selectable = changes.find((change) => change.path === 'ai.user_selectable')
    if (Array.isArray(selectable?.value) && selectable.value.includes('openai')) {
      const problem = { message: 'openai needs OPENAI_API_KEY', path: 'ai.user_selectable.0', code: 'ai_key_missing', params: { provider: 'openai', variable: 'OPENAI_API_KEY' } }
      return json({ detail: 'The app would not start with these settings', code: 'settings_refused', problems: [problem] }, 422)
    }
    if (changes.some((change) => change.path === 'accounts.google_allowed_emails' && Array.isArray(change.value) && change.value.includes('boom'))) {
      const problem = { message: 'Too long', path: 'accounts.google_allowed_emails', code: 'too_long', params: { max_length: 2 } }
      return json({ detail: 'The app would not start with these settings', code: 'settings_refused', problems: [problem] }, 422)
    }
    state.saves += 1
    state.fields = state.fields.map((item) => {
      const change = changes.find((candidate) => candidate.path === item.path)
      return change ? { ...item, value: change.value } : item
    })
    return json(state.fields)
  })
  return { state, sent, fetch }
}

function renderPage(server: ReturnType<typeof fakeServer>, user = TEST_ADMIN, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
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
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
        <Toaster />
      </QueryClientProvider>
    </I18nextProvider>,
  )
  return router
}

const saveButton = () => screen.getByRole('button', { name: 'Save' })
const changesOf = (server: ReturnType<typeof fakeServer>) => server.sent.find((request) => request.method === 'PUT')?.body?.changes

async function saveWith(user: ReturnType<typeof userEvent.setup>, password = PASSWORD) {
  await user.click(saveButton())
  const dialog = await screen.findByRole('dialog', { name: 'Save the settings?' })
  await user.type(within(dialog).getByLabelText('Your password'), password)
  await user.click(within(dialog).getByRole('button', { name: 'Save and apply' }))
  return dialog
}

async function openAdvanced(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Advanced', expanded: false }))
}

describe('the settings page', { timeout: 30_000 }, () => {
  beforeAll(() => {
    Element.prototype.scrollIntoView = () => undefined
    Element.prototype.hasPointerCapture = () => false
    Element.prototype.releasePointerCapture = () => undefined
  })

  afterEach(() => {
    // The page leaves before the session ends: a sign-out under an open form keeps its draft for the next visit.
    cleanup()
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('shows every setting as something to choose: a switch, buttons, a list, checkboxes, a slider, a date', async () => {
    renderPage(fakeServer())

    expect(await screen.findByRole('switch', { name: 'Open registration' })).toBeChecked()
    const watchlist = screen.getByRole('radiogroup', { name: 'Watchlist' })
    expect(within(watchlist).getAllByRole('radio').map((radio) => radio.textContent)).toEqual(['Off', 'Administrators', 'Everyone'])
    expect(within(watchlist).getByRole('radio', { name: 'Everyone' })).toBeChecked()
    expect(screen.getByRole('combobox', { name: 'Default AI model' }), 'more than four options are a list').toHaveTextContent('Claude')
    expect(screen.getByRole('combobox', { name: 'Sign-in window (minutes)' }), 'a step reads with its unit').toHaveTextContent('15 min')
    expect(screen.getByRole('group', { name: 'Models users may pick' })).toBeInTheDocument()
    const temperature = screen.getByRole('slider', { name: 'Temperature' })
    expect(temperature).toHaveValue('0.7')
    expect([temperature.getAttribute('min'), temperature.getAttribute('max'), temperature.getAttribute('step')]).toEqual(['0', '2', '0.1'])
    expect(screen.getByLabelText('Bond ETFs tax-free until')).toHaveAttribute('type', 'date')
    expect(screen.getByRole('radiogroup', { name: 'Initial strategy' }), 'an option the server names at runtime shows as it is').toHaveTextContent('balancedmomentum')
    expect(screen.getByRole('combobox', { name: 'Formula in use' }), 'names too long to stand side by side are a list').toHaveTextContent('Revenue acceleration + near the high')
    expect(within(screen.getByRole('group', { name: 'Times offered for the scheduled follow' })).getByRole('checkbox', { name: '09:05' }), 'a time reads without its seconds').toBeChecked()
    expect(screen.queryByRole('spinbutton'), 'no number is typed').not.toBeInTheDocument()
    expect(screen.queryByText(/appsetting\.yaml/)).not.toBeInTheDocument()
    expect(saveButton()).toBeDisabled()
  })

  it('groups the settings by what the administrator comes to do, with a list that jumps to each group', async () => {
    renderPage(fakeServer())

    await screen.findByRole('switch', { name: 'Open registration' })
    const titles = ['Site and access', 'Features shown', 'Monthly ranking', 'AI', 'Trading and limits', 'Advanced']
    expect(screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)).toEqual(titles)
    expect(within(screen.getByRole('navigation', { name: 'Jump to a group' })).getAllByRole('button').map((button) => button.textContent)).toEqual(titles)
    const site = screen.getByRole('region', { name: 'Site and access' })
    expect(within(site).getByText('Whom the site is for, who may register and sign in, how much each user may run at once, and how much the server logs.')).toBeInTheDocument()
    expect(within(site).getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent), 'a sub-heading per YAML section').toEqual(['Site', 'Accounts and usage'])
  })

  it('keeps the operator’s typed settings folded until asked for, and opens them for a search that finds one', async () => {
    renderPage(fakeServer())
    const user = userEvent.setup()

    const advanced = await screen.findByRole('region', { name: 'Advanced' })
    expect(within(advanced).getByText(/a wrong value can stop a part of the site/i)).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Google users' })).not.toBeInTheDocument()

    await user.click(within(screen.getByRole('navigation', { name: 'Jump to a group' })).getByRole('button', { name: 'Advanced' }))
    expect(screen.getByRole('textbox', { name: 'Google users' })).toHaveValue('latest\nnews')
    await user.click(within(advanced).getByRole('button', { name: 'Advanced', expanded: true }))
    expect(screen.queryByRole('textbox', { name: 'Google users' })).not.toBeInTheDocument()

    await user.type(screen.getByRole('searchbox', { name: 'Find a setting' }), 'id of each provider')
    expect(screen.getByRole('textbox', { name: 'Model id of each provider' })).toHaveValue(JSON.stringify({ claude: 'claude-haiku-5-5' }, null, 2))
    expect(screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)).toEqual(['Advanced'])
  })

  it('shows a setting that changes only at a restart as text, with the reason, and no control', async () => {
    renderPage(fakeServer())

    const row = (await screen.findByText('Development (dev)')).closest('[id="setting-environment"]') as HTMLElement
    expect(within(row).getByText('Changes only when the app restarts.')).toBeInTheDocument()
    expect(within(row).queryByRole('radiogroup')).not.toBeInTheDocument()
  })

  it('saves only the changed settings with the password, and shows the saved values', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Decrease Temperature' }))
    expect(screen.getByRole('group', { name: 'Temperature' })).toHaveTextContent('0.6')
    await user.click(screen.getByRole('switch', { name: 'Open registration' }))
    await user.click(within(screen.getByRole('radiogroup', { name: 'Watchlist' })).getByRole('radio', { name: 'Administrators' }))
    await saveWith(user)

    await waitFor(() => expect(server.state.saves).toBe(1))
    expect(server.sent.find((request) => request.method === 'PUT')?.body).toEqual({
      confirm: true,
      password: PASSWORD,
      changes: [
        { path: 'ai.temperature', value: 0.6 },
        { path: 'accounts.registration_open', value: false },
        { path: 'features.watchlist', value: 'administrators' },
      ],
    })
    expect(await screen.findByText('Saved. The server runs on the new settings now.')).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: 'Temperature' })).toHaveValue('0.6')
    expect(screen.getByRole('switch', { name: 'Open registration' })).not.toBeChecked()
    expect(within(screen.getByRole('radiogroup', { name: 'Watchlist' })).getByRole('radio', { name: 'Administrators' })).toBeChecked()
    expect(saveButton()).toBeDisabled()
  })

  it('moves a number with the slider, and one with no upper end with minus and plus alone', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    fireEvent.change(await screen.findByRole('slider', { name: 'Temperature' }), { target: { value: '1.2' } })
    const day = screen.getByRole('group', { name: 'Decision day of the month' })
    expect(within(day).queryByRole('slider')).not.toBeInTheDocument()
    await user.click(within(day).getByRole('button', { name: 'Increase Decision day of the month' }))
    expect(day).toHaveTextContent('11')
    await saveWith(user)

    await waitFor(() => expect(server.state.saves).toBe(1))
    expect(changesOf(server)).toEqual([{ path: 'ai.temperature', value: 1.2 }, { path: 'ranking.decision_day', value: 11 }])
  })

  it('shows a value of the file that is none of the steps as the current custom value, and leaves it alone through a save of another setting', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    const stopLoss = await screen.findByRole('combobox', { name: 'Stop loss (share of the buy price)' })
    expect(stopLoss).toHaveTextContent('7% (current custom value)')
    await user.click(stopLoss)
    expect((await screen.findAllByRole('option')).map((option) => option.textContent)).toEqual(['5%', '7% (current custom value)', '8%', '10%'])
    await user.click(screen.getByRole('option', { name: '8%' }))
    await user.click(screen.getByRole('combobox', { name: 'Stop loss (share of the buy price)' }))
    await user.click(await screen.findByRole('option', { name: '7% (current custom value)' }))
    expect(saveButton(), 'picking the custom value again is no change').toBeDisabled()

    await user.click(screen.getByRole('switch', { name: 'Open registration' }))
    await saveWith(user)

    await waitFor(() => expect(server.state.saves).toBe(1))
    expect(changesOf(server)).toEqual([{ path: 'accounts.registration_open', value: false }])
    expect(server.state.fields.find((item) => item.path === 'analysis.stop_loss_pct')?.value).toBe(0.07)
  })

  it('offers “not set” for a setting that may be unset, and sends null for it', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()

    const cap = await screen.findByRole('combobox', { name: 'Most shares filled per order' })
    expect(cap).toHaveTextContent('Not set')
    await user.click(cap)
    await user.click(await screen.findByRole('option', { name: '5,000' }))
    await saveWith(user)
    await waitFor(() => expect(server.state.saves).toBe(1))
    expect(changesOf(server)).toEqual([{ path: 'mock_trading.max_fill_quantity', value: 5000 }])

    await user.click(screen.getByRole('combobox', { name: 'Most shares filled per order' }))
    await user.click(await screen.findByRole('option', { name: 'Not set' }))
    await saveWith(user)
    await waitFor(() => expect(server.state.saves).toBe(2))
    expect(server.sent.filter((request) => request.method === 'PUT')[1]?.body?.changes).toEqual([{ path: 'mock_trading.max_fill_quantity', value: null }])
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

  it('holds typed JSON that does not parse at its field, in the refusal’s words, and keeps Save off', async () => {
    renderPage(fakeServer())
    const user = userEvent.setup()
    await openAdvanced(user)

    const models = screen.getByRole('textbox', { name: 'Model id of each provider' })
    await user.clear(models)
    await user.type(models, 'claude')

    expect(models).toHaveAccessibleDescription(/Must be valid JSON\./)
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

  it('opens the folded settings again when a refused save has a problem in one of them', async () => {
    const server = fakeServer()
    renderPage(server)
    const user = userEvent.setup()
    await openAdvanced(user)

    await user.type(screen.getByRole('textbox', { name: 'Google users' }), '\nboom')
    await user.click(screen.getByRole('button', { name: 'Advanced', expanded: true }))
    await saveWith(user)

    expect(await screen.findByRole('textbox', { name: 'Google users' })).toHaveAccessibleDescription(/Must hold at most 2 items\./)
    expect(server.state.saves).toBe(0)
  })

  it('edits a list one item per line, and asks before leaving with a change unsaved', async () => {
    const server = fakeServer()
    const router = renderPage(server)
    const user = userEvent.setup()
    await openAdvanced(user)

    const triggers = screen.getByRole('textbox', { name: 'Google users' })
    expect(triggers).toHaveValue('latest\nnews')
    await user.type(triggers, '\ntoday')
    void router.navigate('/elsewhere')

    const leave = await screen.findByRole('alertdialog', { name: 'Leave this page?' })
    await user.click(within(leave).getByRole('button', { name: 'Keep editing' }))
    await saveWith(user)

    await waitFor(() => expect(server.state.saves).toBe(1))
    expect(changesOf(server)).toEqual([{ path: 'accounts.google_allowed_emails', value: ['latest', 'news', 'today'] }])
  })

  it('keeps the form and its unsaved change when a reload in the background fails', async () => {
    const server = fakeServer()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderPage(server, TEST_ADMIN, client)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('switch', { name: 'Open registration' }))
    const changed = screen.getByRole('switch', { name: 'Open registration' }).getAttribute('aria-checked')

    server.state.down = true
    await act(() => client.refetchQueries())

    expect(screen.getByRole('switch', { name: 'Open registration' })).toHaveAttribute('aria-checked', changed)
    expect(saveButton()).toBeEnabled()
    expect(screen.queryByText('The settings could not be read.')).not.toBeInTheDocument()
  })

  it('hands an unsaved change back when the session ended under the form and the same administrator signs in again', async () => {
    renderPage(fakeServer())
    const user = userEvent.setup()
    const before = (await screen.findByRole('switch', { name: 'Open registration' })).getAttribute('aria-checked')
    await user.click(screen.getByRole('switch', { name: 'Open registration' }))

    act(() => session.expire(session.generation()))
    expect(await screen.findByText('You were signed out')).toBeInTheDocument()
    act(() => session.signIn(TEST_ADMIN))

    expect(await screen.findByRole('switch', { name: 'Open registration' })).not.toHaveAttribute('aria-checked', before)
    expect(saveButton()).toBeEnabled()
  })

  it('clears a search that hides the setting a refused save is about', async () => {
    renderPage(fakeServer())
    const user = userEvent.setup()
    const offered = await screen.findByRole('group', { name: 'Models users may pick' })
    await user.click(within(offered).getByRole('checkbox', { name: 'OpenAI' }))
    await user.type(screen.getByRole('searchbox', { name: 'Find a setting' }), 'registration')
    expect(screen.queryByRole('group', { name: 'Models users may pick' })).not.toBeInTheDocument()

    await saveWith(user)

    expect(await screen.findByText('openai needs OPENAI_API_KEY in the environment or .env, or the app would not start.')).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: 'Find a setting' })).toHaveValue('')
  })

  it('tells a user without the role that the page is for administrators, and asks the server nothing', async () => {
    const server = fakeServer()
    renderPage(server, TEST_USER)

    expect(await screen.findByText('For administrators only')).toBeInTheDocument()
    expect(server.fetch).not.toHaveBeenCalled()
  })
})
