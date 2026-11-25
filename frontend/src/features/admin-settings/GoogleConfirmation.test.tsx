import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { Toaster } from 'sonner'
import { initI18n } from '@/i18n'
import { session, startGoogleConfirmation, takePendingSave } from '@/shared/api'
import { TEST_ADMIN } from '@/test/users'
import { AdminSettingsPage } from './AdminSettingsPage'
import type { SettingField } from './form'

const GOOGLE_ONLY_ADMIN = { ...TEST_ADMIN, has_password: false }
const STORAGE_KEY = 'stock-agent.settings-confirmation'
const TEMPERATURE: SettingField = {
  path: 'ai.temperature',
  kind: 'range',
  group: 'ai',
  value: 0.7,
  options: [],
  steps: [],
  minimum: 0,
  maximum: 2,
  step: 0.1,
  unit: null,
  nullable: false,
  restart_only: false,
}

const ORDERING: SettingField = { ...TEMPERATURE, path: 'features.sinopac_ordering', kind: 'choice', group: 'features', value: 'administrators', options: ['off', 'administrators', 'everyone'], minimum: null, maximum: null, step: null }

/** The settings API in memory: a save needs the confirmation id the test says Google granted. */
function fakeServer(granted: string | null) {
  const saves: Record<string, unknown>[] = []
  const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { 'Content-Type': 'application/json' } })
  const fetch = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
    if ((init?.method ?? 'GET') === 'GET') return json([TEMPERATURE, ORDERING])
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>
    saves.push(body)
    if (body.google_confirmation !== granted) return json({ detail: 'Confirm the save with a fresh Google sign-in.', code: 'google_confirmation_required' }, 403)
    return json([{ ...TEMPERATURE, value: 0.3 }])
  })
  return { saves, fetch }
}

/** Whether closing or reloading the tab now asks the browser's own question. */
function unloadAsks() {
  const leaving = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(leaving)
  return leaving.defaultPrevented
}

function renderPage(server: ReturnType<typeof fakeServer>, entry = '/admin/settings') {
  vi.stubGlobal('fetch', server.fetch)
  const i18n = initI18n('en')
  void i18n.changeLanguage('en')
  session.signIn(GOOGLE_ONLY_ADMIN)
  const router = createMemoryRouter(
    [
      { path: '/admin/settings', element: <AdminSettingsPage /> },
      { path: '/account/sinopac', element: <p>The SinoPac account</p> },
    ],
    { initialEntries: [entry] },
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

describe('a settings save by an administrator without a password', { timeout: 30_000 }, () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = () => undefined
    sessionStorage.clear()
  })

  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('asks to confirm with Google, never for a password', async () => {
    const user = userEvent.setup({ delay: null })
    renderPage(fakeServer(null))

    fireEvent.change(await screen.findByRole('slider', { name: 'Temperature' }), { target: { value: '0.3' } })
    await user.click(screen.getByRole('button', { name: 'Save' }))

    const dialog = await screen.findByRole('alertdialog', { name: 'Save the settings?' })
    expect(within(dialog).getByRole('button', { name: 'Confirm with Google' })).toBeVisible()
    expect(within(dialog).queryByLabelText('Your password')).not.toBeInTheDocument()
  })

  it('lets the browser go to Google without asking, and still asks before a link leaves the change while the page stays', async () => {
    const user = userEvent.setup({ delay: null })
    const router = renderPage(fakeServer(null))

    fireEvent.change(await screen.findByRole('slider', { name: 'Temperature' }), { target: { value: '0.3' } })
    expect(unloadAsks()).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await user.click(within(await screen.findByRole('alertdialog', { name: 'Save the settings?' })).getByRole('button', { name: 'Confirm with Google' }))

    // jsdom loads no other document ("Not implemented: navigation"), so the page stays, as one the back button
    // brings from the bfcache.
    expect(takePendingSave()?.changes).toEqual([{ path: 'ai.temperature', value: 0.3 }])
    expect(unloadAsks()).toBe(false)
    void router.navigate('/account/sinopac')
    expect(await screen.findByRole('alertdialog', { name: 'Leave this page?' })).toBeVisible()
    expect(router.state.location.pathname).toBe('/admin/settings')
  })

  it('keeps the changes under a fresh id while the browser goes to the start of the confirmation', () => {
    const visited: string[] = []
    startGoogleConfirmation({ changes: [{ path: 'ai.temperature', value: 0.3 }], navigate: (address) => visited.push(address) })

    const pending = takePendingSave()
    expect(pending?.changes).toEqual([{ path: 'ai.temperature', value: 0.3 }])
    expect(pending?.id).toMatch(/^[0-9a-f]{32}$/)
    expect(visited).toEqual([`/v1/auth/google/start?confirmation=${pending?.id}`])
    expect(takePendingSave()).toBeNull()
  })

  it('sends the waiting save with the confirmation once Google confirmed it, and clears the address', async () => {
    const server = fakeServer('a'.repeat(32))
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ id: 'a'.repeat(32), changes: [{ path: 'ai.temperature', value: 0.3 }] }))
    const router = renderPage(server, '/admin/settings?google=confirmed')

    expect(await screen.findByText('Saved. The server runs on the new settings now.')).toBeVisible()
    expect(server.saves).toEqual([{ confirm: true, changes: [{ path: 'ai.temperature', value: 0.3 }], google_confirmation: 'a'.repeat(32) }])
    expect(screen.getByRole('slider', { name: 'Temperature' })).toHaveValue('0.3')
    expect(router.state.location.search).toBe('')
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('goes back to the page the save was made on once the settings page sent it', async () => {
    const server = fakeServer('d'.repeat(32))
    const changes = [
      { path: 'shioaji.server', value: 'production' },
      { path: 'features.sinopac_ordering', value: 'off' },
    ]
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ id: 'd'.repeat(32), changes, returnTo: '/account/sinopac' }))
    const router = renderPage(server, '/admin/settings?google=confirmed')

    expect(await screen.findByText('The SinoPac account')).toBeVisible()
    expect(server.saves).toEqual([{ confirm: true, changes, google_confirmation: 'd'.repeat(32) }])
    expect(router.state.location.pathname).toBe('/account/sinopac')
  })

  it('never goes back to an address outside the site that the storage names', () => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ id: 'e'.repeat(32), changes: [], returnTo: '//elsewhere.example' }))

    expect(takePendingSave()).toEqual({ id: 'e'.repeat(32), changes: [] })
  })

  it('says why Google did not confirm, sends nothing and keeps what was typed', async () => {
    const server = fakeServer(null)
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ id: 'b'.repeat(32), changes: [{ path: 'ai.temperature', value: 0.3 }] }))
    renderPage(server, '/admin/settings?google=stale_authentication')

    expect(await screen.findByText(/Google did not ask you to sign in again/)).toBeVisible()
    await waitFor(() => expect(screen.getByRole('slider', { name: 'Temperature' })).toHaveValue('0.3'))
    expect(server.saves).toEqual([])
  })

  it('says to save again when the server no longer holds the confirmation', async () => {
    const server = fakeServer('another-id')
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ id: 'c'.repeat(32), changes: [{ path: 'ai.temperature', value: 0.3 }] }))
    renderPage(server, '/admin/settings?google=confirmed')

    expect(await screen.findByText(/used already or took too long/)).toBeVisible()
    expect(screen.getByRole('slider', { name: 'Temperature' })).toHaveValue('0.3')
  })
})
