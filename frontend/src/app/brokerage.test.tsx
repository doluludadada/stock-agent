import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type Schemas, type User } from '@/shared/api'
import { siteShowing } from '@/test/features'
import { TEST_ADMIN } from '@/test/users'
import { BrokerageRoute } from './router/routes/brokerage'

const PASSWORD = 'correct horse battery'
const HOLDER: User = { ...TEST_ADMIN, permissions: [...TEST_ADMIN.permissions, 'use_real_broker'] }
const ON_SIMULATION: Schemas['BrokerageAccountResponse'] = {
  server: 'simulation',
  switch_refusal: null,
  login_up: false,
  login_down: true,
  ordering: true,
  simulation_initial_cash: 1_000_000,
  statement: null,
}

/**
 * The SinoPac page's reads and the settings save, which needs the password and may answer a refusal of the settings.
 * As the server does, a confirmed save writes its turn-off of ordering first, so a refused one leaves ordering off too, and
 * the account read again says why a switch is refused now (`switchRefusal`).
 */
function fakeServer(refusal: Schemas['SettingsProblem'] | null = null, switchRefusal: Schemas['ServerSwitchRefusal'] | null = null) {
  const saves: unknown[] = []
  let account = ON_SIMULATION
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const { pathname } = new URL(input, 'http://localhost')
      if (pathname === '/v1/auth/status') return json(siteShowing())
      if (pathname === '/v1/account/brokerage') return json(account)
      if (pathname !== '/v1/admin/settings' || init?.method !== 'PUT') return json({ detail: 'Not found.', code: 'not_found' }, 404)
      const body = JSON.parse(String(init.body)) as { password?: string; changes: Schemas['SettingChange'][] }
      saves.push(body)
      if (body.password !== PASSWORD) return json({ detail: 'The password is wrong.', code: 'password_refused' }, 403)
      if (body.changes.some((change) => change.path === 'features.sinopac_ordering' && change.value === 'off')) account = { ...account, ordering: false }
      if (refusal) {
        account = { ...account, switch_refusal: switchRefusal }
        return json({ detail: 'The app would not start with these settings', code: 'settings_refused', problems: [refusal] }, 422)
      }
      const server = body.changes.find((change) => change.path === 'shioaji.server')?.value
      if (server === 'production' || server === 'simulation') account = { ...account, server }
      return json([])
    }),
  )
  return saves
}

function open() {
  session.signIn(HOLDER)
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <BrokerageRoute />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

async function switchToProduction(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Switch to Production…' }))
  const dialog = await screen.findByRole('dialog', { name: 'Switch to Production?' })
  await user.type(within(dialog).getByLabelText('Type Production to confirm'), 'Production')
  await user.type(within(dialog).getByLabelText('Your password'), PASSWORD)
  await user.click(within(dialog).getByRole('button', { name: 'Save and apply' }))
}

describe('the SinoPac page’s switch, through the settings save', { timeout: 30_000 }, () => {
  afterEach(() => {
    cleanup()
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('sends the server and ordering off as one save with the administrator’s password', async () => {
    const user = userEvent.setup({ delay: null })
    const saves = fakeServer()
    open()

    await switchToProduction(user)

    expect(saves).toEqual([
      {
        confirm: true,
        changes: [
          { path: 'shioaji.server', value: 'production' },
          { path: 'features.sinopac_ordering', value: 'off' },
        ],
        password: PASSWORD,
      },
    ])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('holds the password dialog shut until the server’s name is typed', async () => {
    const user = userEvent.setup({ delay: null })
    fakeServer()
    open()

    await user.click(await screen.findByRole('button', { name: 'Switch to Production…' }))
    const dialog = await screen.findByRole('dialog', { name: 'Switch to Production?' })
    await user.type(within(dialog).getByLabelText('Your password'), PASSWORD)

    expect(within(dialog).getByRole('button', { name: 'Save and apply' })).toBeDisabled()
  })

  it('says in its own words why the switch is refused now, and holds its button', async () => {
    const user = userEvent.setup({ delay: null })
    fakeServer(
      { message: 'refused', path: 'accounts.registration_open', file: null, line: null, column: null, code: null, params: {} },
      { reason: 'registration_open', server: 'production', missing: [] },
    )
    open()

    await switchToProduction(user)

    expect(await screen.findByText('Production refuses open registration. Close registration on the settings page first.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Switch to Production…' })).toBeDisabled()
  })

  it('reads the account again after a refused switch, and says that ordering was turned off and is off now', async () => {
    const user = userEvent.setup({ delay: null })
    fakeServer(
      { message: 'refused', path: 'shioaji.server', file: null, line: null, column: null, code: null, params: {} },
      { reason: 'credentials_missing', server: 'production', missing: ['SHIOAJI_CA_PATH'] },
    )
    open()
    expect((await screen.findAllByText('Ordering on'))[0]).toBeVisible()

    await switchToProduction(user)

    const refusal = await screen.findByRole('alert')
    expect(refusal).toHaveTextContent('The server refused the save.')
    expect(await screen.findByText('SHIOAJI_CA_PATH')).toBeVisible()
    expect(await within(refusal).findByText(/Ordering on SinoPac was turned off before the switch and is off now\./)).toBeVisible()
    expect(screen.getAllByText('Ordering off')[0]).toBeVisible()
    expect(screen.queryAllByText('Ordering on')).toEqual([])
    expect(screen.getByText('SinoPac’s Simulation server: no real money.'), 'the server stays where it was').toBeVisible()
  })

  it('reads the account again after a saved switch', async () => {
    const user = userEvent.setup({ delay: null })
    fakeServer()
    open()

    await switchToProduction(user)

    expect(await screen.findByText('SinoPac’s Production server: the real account, real money.')).toBeVisible()
    expect(screen.getAllByText('Ordering off')[0]).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
