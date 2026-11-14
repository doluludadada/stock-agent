import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type User } from '@/shared/api'
import { siteShowing } from '@/test/features'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import type { BrokerageAccount, BrokerageStatement } from './api'
import { BrokerageAccountPage } from './BrokerageAccountPage'

const HOLDER: User = { ...TEST_ADMIN, permissions: [...TEST_ADMIN.permissions, 'use_real_broker'] }

const STATEMENT: BrokerageStatement = {
  read_at: '2026-11-13T06:00:00Z',
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
const SIMULATION: BrokerageAccount = { simulation: true, login_up: true, ordering: false, statement: STATEMENT }

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

function open(user: User = HOLDER) {
  session.signIn(user)
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <BrokerageAccountPage />
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
  })

  it('says at the top that it shows the simulation server, and that ordering is off', async () => {
    serve(() => json(SIMULATION))
    open()

    expect(await screen.findByText('Simulation server, no real money')).toBeVisible()
    expect(screen.queryByText('Real account')).not.toBeInTheDocument()
    expect(screen.getByText(ORDERING_OFF)).toBeVisible()
    expect(screen.getByText('The broker’s own figures, read 11/13/2026, 14:00.')).toBeVisible()
    expect(await screen.findByRole('link', { name: 'My holdings' })).toHaveAttribute('href', '/holdings')
  })

  it('says it shows the real account, and that a run started on SinoPac can order within the BUY limits', async () => {
    serve(() => json({ ...SIMULATION, simulation: false, ordering: true }))
    open()

    expect(await screen.findByText('Real account')).toBeVisible()
    expect(screen.queryByText('Simulation server, no real money')).not.toBeInTheDocument()
    expect(screen.getByText('Ordering on')).toBeVisible()
    expect(screen.queryByText(ORDERING_OFF)).not.toBeInTheDocument()
  })

  it('reads the statement in order: the figures, the holdings, what is due, today’s deals, the past sales, the site’s orders', async () => {
    const asked = serve(() => json(SIMULATION))
    open()

    expect((await screen.findByText('Bank balance')).parentElement).toHaveTextContent('405,000')
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
    const asked = serve(() => json({ ...SIMULATION, login_up: false, statement: null }))
    open()

    expect(await screen.findByText('The site’s SinoPac login is down')).toBeVisible()
    expect(screen.getByText('The site reconnects by itself.')).toBeVisible()
    expect(screen.getByText('Simulation server, no real money'), 'the server still says which it is').toBeVisible()
    expect(screen.getByText(ORDERING_OFF)).toBeVisible()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(asked.filter((url) => url.startsWith('/v1/account/trades'))).toEqual([])
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

  it('shows any other failure as an error with a retry', async () => {
    serve(() => json({ detail: 'Boom.' }, 500))
    open()

    expect(await screen.findByText('The SinoPac account could not be loaded.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible()
  })
})
