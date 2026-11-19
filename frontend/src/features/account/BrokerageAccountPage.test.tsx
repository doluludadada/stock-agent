import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type User } from '@/shared/api'
import { siteShowing } from '@/test/features'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import type { BrokerageAccount, BrokerageStatement } from './api'
import { BrokerageAccountPage } from './BrokerageAccountPage'
import type { SaveConfirmationProps } from '@/shared/api'

const HOLDER: User = { ...TEST_ADMIN, permissions: [...TEST_ADMIN.permissions, 'use_real_broker'] }

const STATEMENT: BrokerageStatement = {
  read_at: '2026-11-13T06:00:00Z',
  simulation: false,
  balance: 405_000,
  settlements: [
    { settles_on: '2026-11-16', amount: -51_273 },
    { settles_on: '2026-11-17', amount: 20_100 },
  ],
  positions: [{ stock_id: '2330', quantity: 1037, average_cost: 500, mark_price: 600, marked_at: '2026-11-13T05:30:00Z', market_value: 619_000, unrealized_pnl: 100_500, cost_basis: 518_500, unrealized_return: 0.1938, opened_at: null }],
  fills: [{ stock_id: '2317', action: 'buy', quantity: 500, price: 102.5, filled_on: '2026-11-13' }],
  sales: [{ stock_id: '2317', action: 'sell', quantity: 1000, price: 110, filled_on: '2026-10-20', realized_pnl: 7_250 }],
  sales_from: '2026-08-15',
  market_value: 619_000,
  unrealized_pnl: 100_500,
  realized_pnl: 7_250,
}
const SIMULATION: BrokerageAccount = {
  server: 'simulation',
  switch_refusal: null,
  login_up: true,
  login_down: false,
  ordering: false,
  simulation_initial_cash: 1_000_000,
  statement: { ...STATEMENT, simulation: true },
}
const PRODUCTION: BrokerageAccount = { ...SIMULATION, server: 'production', simulation_initial_cash: null, statement: STATEMENT }

const NOT_ANSWERING = { detail: 'Shioaji answered TimeoutError', code: 'broker_not_answering' }

const LISTING: Record<string, string> = { '2330': '台積電', '2317': '鴻海' }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function serve(account: () => Response) {
  const asked: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      asked.push(url)
      const { pathname, searchParams } = new URL(url, 'http://localhost')
      if (pathname === '/v1/auth/status') return json(siteShowing())
      if (pathname === '/v1/account/brokerage') return account()
      if (pathname === '/v1/account/trades') return json([])
      if (pathname === '/v1/market/stocks') {
        const code = searchParams.get('query') ?? ''
        return json(LISTING[code] ? [{ stock_id: code, name: LISTING[code], market: 'twse', today: null }] : [])
      }
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  return asked
}

/**
 * The settings save's confirmation as far as this page sees it: the dialog says the page's words and what it holds, and
 * its confirm, held until the page's own field is filled, saves `changes` here. The settings feature's own dialog and
 * save are tested on their page and in app/brokerage.test.tsx.
 */
function recordingConfirmation(saved: SaveConfirmationProps['changes'][]) {
  return function Confirmation({ open, changes, onSaved, title, description, children, ready = true }: SaveConfirmationProps) {
    if (!open) return null
    return (
      <dialog open aria-label={title}>
        <p>{description}</p>
        {children}
        <button
          type="button"
          disabled={!ready}
          onClick={() => {
            saved.push(changes)
            onSaved()
          }}
        >
          Confirm
        </button>
      </dialog>
    )
  }
}

function open(user: User = HOLDER, saved: SaveConfirmationProps['changes'][] = []) {
  session.signIn(user)
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <BrokerageAccountPage Confirmation={recordingConfirmation(saved)} />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

const ORDERING_OFF = 'Ordering off'

describe('the SinoPac account', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    focusManager.setFocused(undefined)
  })

  it('says at the top that it is the SinoPac account on Simulation, logged in, and that ordering is off', async () => {
    serve(() => json(SIMULATION))
    open()

    expect(await screen.findByText('SinoPac’s Simulation server: no real money.')).toBeVisible()
    expect(screen.getAllByText('Simulation')[0], 'the server’s label').toBeVisible()
    expect(screen.getByText('Logged in')).toBeVisible()
    expect(screen.queryByText(/real account/)).not.toBeInTheDocument()
    expect(screen.getAllByText(ORDERING_OFF)[0]).toBeVisible()
    expect(screen.getByText('The broker’s own figures, read 11/13/2026, 14:00.')).toBeVisible()
    expect(await screen.findByRole('link', { name: 'My holdings' })).toHaveAttribute('href', '/holdings')
  })

  it('says it shows the real account, and that a run started on SinoPac can order within the BUY limits', async () => {
    serve(() => json({ ...PRODUCTION, ordering: true }))
    open()

    expect(await screen.findByText('SinoPac’s Production server: the real account, real money.')).toBeVisible()
    expect((await screen.findByText('Bank balance')).parentElement).toHaveTextContent('405,000')
    expect(screen.queryByText(/the cash here is the site’s figure/)).not.toBeInTheDocument()
    expect(screen.queryByText('SinoPac’s Simulation server: no real money.')).not.toBeInTheDocument()
    expect(screen.getAllByText('Ordering on')[0]).toBeVisible()
    expect(screen.queryByText(ORDERING_OFF)).not.toBeInTheDocument()
  })

  it('reads the statement in order: the figures, the holdings, what is due, today’s deals, the past sales, the site’s orders', async () => {
    const asked = serve(() => json(SIMULATION))
    open()

    expect((await screen.findByText('Cash (the site’s figure)')).parentElement).toHaveTextContent('405,000')
    expect(screen.queryByText('Bank balance')).not.toBeInTheDocument()
    expect(
      screen.getByText(
        'SinoPac’s Simulation reports no cash balance, so the cash here is the site’s figure: the account’s starting cash on Simulation (a setting), less what the holdings and today’s purchases cost, plus the profit and loss of every sale SinoPac lists, taken as after fees and tax.',
      ),
    ).toBeVisible()
    expect(screen.getByText('Realized P&L since 8/15').parentElement).toHaveTextContent('+7,250')

    const [held] = within(screen.getByRole('table', { name: 'Holdings' })).getAllByRole('row').slice(1)
    expect(await within(held!).findByRole('link', { name: /台積電/ })).toHaveAttribute('href', '/stocks/2330')
    expect(held, 'shares, so an odd lot shows').toHaveTextContent('1,037')
    expect(held).toHaveTextContent('600.00')
    expect(held).toHaveTextContent('+100,500')
    expect(held).toHaveTextContent('+19.38%')

    const [toPay, toReceive] = within(screen.getByRole('table', { name: 'Settlements' })).getAllByRole('row').slice(1)
    expect(toPay).toHaveTextContent('-51,273')
    expect(toPay).toHaveTextContent('to pay')
    expect(toReceive).toHaveTextContent('+20,100')
    expect(toReceive).toHaveTextContent('to receive')

    expect(within(screen.getByRole('table', { name: 'Today’s fills' })).getAllByRole('row')[1]).toHaveTextContent('BUY 500 @ 102.50')
    const [sale] = within(screen.getByRole('table', { name: 'Past sales' })).getAllByRole('row').slice(1)
    expect(sale).toHaveTextContent('SELL 1,000 @ 110.00 · 10/20')
    expect(sale).toHaveTextContent('+7,250')

    expect(await screen.findByText('No order of this site has filled on SinoPac.')).toBeVisible()
    expect(asked).toContain('/v1/account/trades?limit=21&offset=0&broker=shioaji')
    expect(asked.filter((url) => url.startsWith('/v1/account/history')), 'the broker’s own figures, not the site’s account history').toEqual([])
  })

  it('with the login down, says so, says the site retries, and asks for nothing of the account', async () => {
    const asked = serve(() => json({ ...SIMULATION, login_up: false, login_down: true, statement: null }))
    open()

    expect(await screen.findByText('The site’s SinoPac login is down')).toBeVisible()
    expect(screen.getByText('The site reconnects by itself.')).toBeVisible()
    expect(screen.getByText('SinoPac’s Simulation server: no real money.'), 'the server still says which it is').toBeVisible()
    expect(screen.getByText('Not logged in')).toBeVisible()
    expect(screen.getAllByText(ORDERING_OFF)[0]).toBeVisible()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(asked.filter((url) => url.startsWith('/v1/account/trades'))).toEqual([])
  })

  it('with the login up but no SinoPac account on it, as after a CA certificate that would not activate, says ordering is unavailable and promises no reconnect', async () => {
    serve(() => json({ ...PRODUCTION, login_up: false, login_down: false, statement: null }))
    open()

    expect(await screen.findByText('SinoPac ordering is unavailable on this login')).toBeVisible()
    expect(screen.getByText(/The server’s log says why\./)).toBeVisible()
    expect(screen.getByText('Unavailable')).toBeVisible()
    expect(screen.queryByText('Not logged in')).not.toBeInTheDocument()
    expect(screen.queryByText('The site reconnects by itself.')).not.toBeInTheDocument()
  })

  it('says each empty list in words', async () => {
    serve(() => json({ ...SIMULATION, statement: { ...STATEMENT, positions: [], settlements: [], fills: [], sales: [] } }))
    open()

    expect(await screen.findByText('The account holds no stock.')).toBeVisible()
    expect(screen.getByText('Nothing to settle.')).toBeVisible()
    expect(screen.getByText('No deal today.')).toBeVisible()
    expect(screen.getByText('No sale since 08/15/2026.')).toBeVisible()
  })

  it('tells a user who may not hold the real broker that the page is for administrators, and asks nothing', async () => {
    const asked = serve(() => json(SIMULATION))
    open(TEST_USER)

    expect(await screen.findByText('For administrators only')).toBeVisible()
    expect(asked.filter((url) => url.startsWith('/v1/account/'))).toEqual([])
  })

  it('answers the server’s administrators-only refusal the same way', async () => {
    serve(() => json({ detail: 'Administrators only.', code: 'administrators_only' }, 403))
    open()

    expect(await screen.findByText('For administrators only')).toBeVisible()
  })

  it('switches to Production only once the server’s name is typed, sending the server and ordering off in one save', async () => {
    const user = userEvent.setup({ delay: null })
    const saved: SaveConfirmationProps['changes'][] = []
    serve(() => json(SIMULATION))
    open(HOLDER, saved)

    await user.click(await screen.findByRole('button', { name: 'Switch to Production…' }))
    const dialog = screen.getByRole('dialog', { name: 'Switch to Production?' })
    expect(within(dialog).getByText('Every order on SinoPac from now on is real money.')).toBeVisible()
    expect(within(dialog).getByText('Ordering on SinoPac turns off. Turn it on again here to order.')).toBeVisible()
    expect(within(dialog).getByText('The SinoPac login restarts on the new server, and the quotes come from it too.')).toBeVisible()
    expect(within(dialog).getByText('A ranking follow, by hand or by schedule, never orders on Production.')).toBeVisible()
    const confirm = within(dialog).getByRole('button', { name: 'Confirm' })
    expect(confirm, 'held until the name is typed').toBeDisabled()

    await user.type(within(dialog).getByLabelText('Type Production to confirm'), 'Productio')
    expect(confirm).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Type Production to confirm'), 'n')
    await user.click(confirm)

    expect(saved).toEqual([
      [
        { path: 'shioaji.server', value: 'production' },
        { path: 'features.sinopac_ordering', value: 'off' },
      ],
    ])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps the switch to Production off and names the variables the server lacks, never asking for a value', async () => {
    serve(() =>
      json({ ...SIMULATION, switch_refusal: { reason: 'credentials_missing', server: 'production', missing: ['SHIOAJI_CA_PATH', 'SHIOAJI_PERSON_ID'], unsettled: 0 } }),
    )
    open()

    expect(await screen.findByRole('button', { name: 'Switch to Production…' })).toBeDisabled()
    expect(screen.getByText('Production needs these variables in the server’s .env, which are not set yet:')).toBeVisible()
    expect(screen.getByText('SHIOAJI_CA_PATH')).toBeVisible()
    expect(screen.getByText('SHIOAJI_PERSON_ID')).toBeVisible()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('on a developer’s machine offers no switch to Production', async () => {
    serve(() => json({ ...SIMULATION, switch_refusal: { reason: 'environment', server: 'production', missing: [], unsettled: 0 } }))
    open()

    expect(await screen.findByRole('button', { name: 'Switch to Production…' })).toBeDisabled()
    expect(screen.getByText('This machine’s environment does not log in to Production.')).toBeVisible()
  })

  it('keeps the switch off while SinoPac orders await settlement and says how many', async () => {
    serve(() => json({ ...SIMULATION, switch_refusal: { reason: 'orders_unsettled', server: 'production', missing: [], unsettled: 2 } }))
    open()

    expect(await screen.findByRole('button', { name: 'Switch to Production…' })).toBeDisabled()
    expect(
      screen.getByText('SinoPac orders awaiting settlement from this server’s record of the day: 2. Switch once none is left, at the latest the next day.'),
    ).toBeVisible()
  })

  it('switches back to Simulation without a typed name, turning ordering off too', async () => {
    const user = userEvent.setup({ delay: null })
    const saved: SaveConfirmationProps['changes'][] = []
    serve(() => json({ ...PRODUCTION, ordering: true }))
    open(HOLDER, saved)

    await user.click(await screen.findByRole('button', { name: 'Switch to Simulation…' }))
    await user.click(within(screen.getByRole('dialog', { name: 'Switch to Simulation?' })).getByRole('button', { name: 'Confirm' }))

    expect(saved).toEqual([
      [
        { path: 'shioaji.server', value: 'simulation' },
        { path: 'features.sinopac_ordering', value: 'off' },
      ],
    ])
  })

  it('turns ordering on for administrators and off again, saying on Production that it is real money', async () => {
    const user = userEvent.setup({ delay: null })
    const saved: SaveConfirmationProps['changes'][] = []
    serve(() => json(PRODUCTION))
    open(HOLDER, saved)

    await user.click(await screen.findByRole('button', { name: 'Turn ordering on…' }))
    const dialog = screen.getByRole('dialog', { name: 'Turn ordering on SinoPac on?' })
    expect(within(dialog).getByText('This account is on Production: every order is real money.')).toBeVisible()
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))

    expect(saved).toEqual([[{ path: 'features.sinopac_ordering', value: 'administrators' }]])
  })

  it('shows the starting cash on Simulation only, as all the money put in, and saves a raise', async () => {
    const user = userEvent.setup({ delay: null })
    const saved: SaveConfirmationProps['changes'][] = []
    serve(() => json(SIMULATION))
    open(HOLDER, saved)

    expect(await screen.findByText('1,000,000')).toBeVisible()
    expect(screen.getByText('All the money put into the Simulation account. To add money, raise it.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Change…' }))
    const field = within(screen.getByRole('dialog', { name: 'Change the starting cash?' })).getByLabelText('Starting cash (NT$)')
    await user.clear(field)
    await user.type(field, '1500000')
    await user.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(saved).toEqual([[{ path: 'shioaji.simulation_initial_cash', value: 1_500_000 }]])
  })

  it('has no starting cash on Production, and nothing to manage for a holder who does not edit the settings', async () => {
    serve(() => json(PRODUCTION))
    open({ ...TEST_USER, permissions: ['use_real_broker'] })

    expect(await screen.findByText('SinoPac’s Production server: the real account, real money.')).toBeVisible()
    expect(screen.queryByRole('button', { name: /Switch to/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Starting cash')).not.toBeInTheDocument()
  })

  it('says in one sentence that SinoPac did not answer, and reads the account again on retry', async () => {
    const answers = [json(NOT_ANSWERING, 503), json(SIMULATION)]
    const asked = serve(() => answers.shift() ?? json(SIMULATION))
    open()

    expect(await screen.findByText('SinoPac did not answer in time. Try again in a moment.')).toBeVisible()
    expect(screen.queryByText(NOT_ANSWERING.detail)).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('SinoPac’s Simulation server: no real money.')).toBeVisible()
    expect(asked.filter((url) => url.startsWith('/v1/account/brokerage'))).toHaveLength(2)
  })

  it('keeps the server, ordering and switch controls through a later read SinoPac did not answer', async () => {
    const answers = [json(SIMULATION), json(NOT_ANSWERING, 503), json(SIMULATION)]
    const asked = serve(() => answers.shift() ?? json(SIMULATION))
    open()
    expect(await screen.findByText('Cash (the site’s figure)')).toBeVisible()

    const later = Date.now() + 61_000
    vi.spyOn(Date, 'now').mockReturnValue(later)
    act(() => {
      focusManager.setFocused(false)
      focusManager.setFocused(true)
    })

    expect(await screen.findByText('SinoPac did not answer in time. Try again in a moment.')).toBeVisible()
    expect(screen.queryByText('Cash (the site’s figure)'), 'the statement the failed read replaces').not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Switch to Production…' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Turn ordering on…' })).toBeEnabled()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Cash (the site’s figure)')).toBeVisible()
    expect(asked.filter((url) => url.startsWith('/v1/account/brokerage'))).toHaveLength(3)
  })

  it('shows any other failure as an error with a retry', async () => {
    serve(() => json({ detail: 'Boom.' }, 500))
    open()

    expect(await screen.findByText('The SinoPac account could not be loaded.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible()
  })
})
