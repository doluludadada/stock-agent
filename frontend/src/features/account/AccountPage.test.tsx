import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type Schemas } from '@/shared/api'
import { siteShowing } from '@/test/features'
import { TEST_USER } from '@/test/users'
import { AccountPage } from './AccountPage'

type History = Schemas['AccountHistoryResponse']
type Trade = Schemas['TradeResponse']

const FULL_CYCLE = '11111111-1111-4111-8111-111111111111'
const FOLLOW_RUN = '22222222-2222-4222-8222-222222222222'
const INTRADAY = '33333333-3333-4333-8333-333333333333'

const unpriced = { stock_id: '2330', quantity: 1000, average_cost: 100, mark_price: 100, marked_at: null, market_value: 100_000, unrealized_pnl: 0, cost_basis: 100_000, unrealized_return: null, opened_at: null, weight: 100_000 / 1_012_000 }
const value = { cash: 912_000, market_value: 100_000, unrealized_pnl: 0, equity: 1_012_000, positions: [unpriced] }
const HISTORY: History = {
  current: value,
  live_stock_ids: [],
  equity_curve: {},
  as_of: null,
  execution_provider: 'mock',
  opening: { initial_cash: 1_000_000, opened_at: '2026-11-04T01:00:00Z' },
  profit: 12_000,
}
const EMPTY: History = { ...HISTORY, current: { cash: 2_000_000, market_value: 0, unrealized_pnl: 0, equity: 2_000_000, positions: [] }, profit: 0 }
const LISTING: Record<string, string> = { '2330': '台積電', '2317': '鴻海' }

function trade(id: string, overrides: Partial<Trade['order']>, run: Trade['run']): Trade {
  return {
    order: {
      id,
      run_id: run.run_id,
      decision_id: `decision-${id}`,
      stock_id: '2330',
      action: 'buy',
      order_type: 'limit',
      quantity: 1000,
      limit_price: 512,
      time_in_force: 'ioc',
      status: 'filled',
      reason: null,
      filled_quantity: 1000,
      average_filled_price: 512,
      fee: 729,
      tax: 0,
      realized_pnl: null,
      created_at: '2026-11-06T02:05:00Z',
      updated_at: '2026-11-06T02:05:00Z',
      ...overrides,
    },
    run,
  }
}

const fullCycle = { run_id: FULL_CYCLE, workflow: 'full_cycle', start_time: '2026-11-05T13:00:00Z' } as const
const intraday = { run_id: INTRADAY, workflow: 'intraday', start_time: '2026-11-06T02:00:00Z' } as const

/**
 * The account endpoints and the listing, as the backend answers them; trades page by `limit` and `offset`. `pastDay`
 * answers a lookup of the account as of a day, null for a server error.
 */
function serve(history: History, trades: Trade[], pastDay?: (day: string) => History | null | Promise<History | null>, site = siteShowing({ ranking: 'off' })) {
  const asked: string[] = []
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      asked.push(url)
      const { pathname, searchParams } = new URL(url, 'http://localhost')
      if (pathname === '/v1/auth/status') return json(site)
      if (pathname === '/v1/market/stocks') {
        const code = searchParams.get('query') ?? ''
        return json(LISTING[code] ? [{ stock_id: code, name: LISTING[code], market: 'twse', today: null }] : [])
      }
      const day = searchParams.get('as_of')
      if (pathname === '/v1/account/history' && day && pastDay) {
        const answer = await pastDay(day)
        return answer ? json(answer) : json({ detail: 'boom' }, 500)
      }
      if (pathname === '/v1/account/history') return json(history)
      if (pathname === '/v1/account/trades') {
        const offset = Number(searchParams.get('offset'))
        return json(trades.slice(offset, offset + Number(searchParams.get('limit'))))
      }
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  return asked
}

function open() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <AccountPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the mock account', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('says a position without a quote is unpriced, and does not also call it a daily close', async () => {
    serve(HISTORY, [])
    open()

    const cell = await screen.findByText(/no quote, at average cost/)
    expect(cell).toHaveTextContent(/^no quote, at average cost$/)
  })

  it('leads with the equity, then the total P&L since the account opened over its starting capital', async () => {
    serve(HISTORY, [])
    open()

    expect(await screen.findByText('1,012,000')).toBeVisible()
    const total = screen.getByText('Total P&L').parentElement!
    expect(total).toHaveTextContent('+12,000')
    expect(total).toHaveTextContent('+1.20%')
    const capital = screen.getByText('Starting capital').parentElement!
    expect(capital).toHaveTextContent('1,000,000')
    expect(capital).toHaveTextContent('since 11/4')
  })

  it('lists each trade with the run it came from, and marks one that came through a follow', async () => {
    serve(HISTORY, [
      trade('t2', { stock_id: '2317', action: 'sell', quantity: 500, filled_quantity: 500, average_filled_price: 101.5, fee: 72, tax: 152, realized_pnl: 3_250 }, intraday),
      trade('t1', { run_id: FOLLOW_RUN }, fullCycle),
    ])
    open()

    const table = within(await screen.findByRole('table', { name: 'Trades' }))
    const [sell, buy] = table.getAllByRole('row').slice(1)

    expect(within(sell!).getByRole('link', { name: /鴻海/ })).toHaveAttribute('href', '/stocks/2317')
    expect(sell).toHaveTextContent('SELL')
    expect(sell).toHaveTextContent('101.50')
    expect(sell).toHaveTextContent('224')
    expect(sell).toHaveTextContent('+3,250')
    expect(within(sell!).getByRole('link', { name: /^Intraday · / })).toHaveAttribute('href', `/runs/${INTRADAY}`)
    expect(within(sell!).queryByText('followed')).not.toBeInTheDocument()

    expect(within(buy!).getByRole('link', { name: /^Full Cycle · 11\/5,? 21:00$/ })).toHaveAttribute('href', `/runs/${FULL_CYCLE}`)
    expect(within(buy!).getByText('followed')).toBeVisible()
    expect(buy).toHaveTextContent('1,000')
    expect(buy).toHaveTextContent('512.00')
  })

  it('shows more trades on request, asking for the next page only then', async () => {
    const trades = Array.from({ length: 23 }, (_, index) => trade(`t${index}`, {}, fullCycle))
    const asked = serve(HISTORY, trades)
    const user = userEvent.setup()
    open()

    const table = await screen.findByRole('table', { name: 'Trades' })
    expect(within(table).getAllByRole('row')).toHaveLength(1 + 20)
    expect(asked.filter((url) => url.startsWith('/v1/account/trades'))).toEqual(['/v1/account/trades?limit=21&offset=0&broker=mock'])

    await user.click(screen.getByRole('button', { name: 'Show more trades' }))
    expect(await within(table).findAllByRole('row')).toHaveLength(1 + 23)
    expect(asked.filter((url) => url.startsWith('/v1/account/trades'))).toEqual(['/v1/account/trades?limit=21&offset=0&broker=mock', '/v1/account/trades?limit=21&offset=20&broker=mock'])
    expect(screen.queryByRole('button', { name: 'Show more trades' })).not.toBeInTheDocument()
  })

  it('with no position and no trade, sends the reader to the monthly ranking to follow it where the site shows the ranking', async () => {
    serve(EMPTY, [], undefined, siteShowing())
    open()

    expect(await screen.findByRole('link', { name: 'Open the monthly ranking' })).toHaveAttribute('href', '/ranking')
    expect(screen.getByText(/^Follow this month’s ranking on the monthly ranking page\./)).toBeVisible()
  })

  it('with no position and no trade, tells how to fill it where the ranking is hidden: follow a finished analysis run', async () => {
    serve(EMPTY, [])
    open()

    expect(await screen.findByText('Nothing in your mock account yet')).toBeVisible()
    expect(screen.getByText(/^Open a finished analysis run and follow its decisions into this account\./)).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open the analysis runs' })).toHaveAttribute('href', '/runs')
    expect(screen.queryByRole('table', { name: 'Trades' })).not.toBeInTheDocument()
  })

  it('while a past day loads, says nothing of the day asked before, then shows the day asked', async () => {
    let release = () => {}
    const held = new Promise<void>((resolve) => (release = resolve))
    serve(HISTORY, [], async (day) => {
      if (day === '2026-11-04') await held
      return { ...HISTORY, as_of: { last_fill_at: `${day}T02:05:00Z`, value: { ...value, equity: day === '2026-11-05' ? 955_000 : 1_000_500 } } }
    })
    const user = userEvent.setup()
    open()

    const card = within(await screen.findByRole('region', { name: 'Account as of a day' }))
    fireEvent.change(card.getByLabelText('Account as of a day'), { target: { value: '2026-11-05' } })
    await user.click(card.getByRole('button', { name: 'Show' }))
    expect(await card.findByText('955,000')).toBeVisible()

    fireEvent.change(card.getByLabelText('Account as of a day'), { target: { value: '2026-11-04' } })
    await user.click(card.getByRole('button', { name: 'Show' }))
    expect(card.queryByText('955,000')).not.toBeInTheDocument()
    expect(card.queryByText(/^As of /)).not.toBeInTheDocument()
    expect(card.getByRole('button', { name: 'Show' })).toBeDisabled()
    expect(screen.getByText('1,012,000')).toBeVisible()

    release()
    expect(await card.findByText('1,000,500')).toBeVisible()
    expect(card.getByRole('button', { name: 'Show' })).toBeEnabled()
  })

  it('keeps the account on screen when a past day fails to load, with the failure and its retry in that card', async () => {
    let failing = true
    serve(HISTORY, [], (day) => (failing ? null : { ...HISTORY, as_of: { last_fill_at: `${day}T02:05:00Z`, value: { ...value, equity: 955_000 } } }))
    const user = userEvent.setup()
    open()

    const card = within(await screen.findByRole('region', { name: 'Account as of a day' }))
    fireEvent.change(card.getByLabelText('Account as of a day'), { target: { value: '2026-11-05' } })
    await user.click(card.getByRole('button', { name: 'Show' }))

    expect(await card.findByText('The account could not be loaded.')).toBeVisible()
    expect(screen.getByText('1,012,000')).toBeVisible()
    expect(screen.getByText(/no quote, at average cost/)).toBeVisible()

    failing = false
    await user.click(card.getByRole('button', { name: 'Try again' }))
    expect(await card.findByText('955,000')).toBeVisible()
  })

  it('is the mock account alone: it asks for no other account and offers no switch to one', async () => {
    const asked = serve(HISTORY, [])
    open()

    expect(await screen.findByText('1,012,000')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Mock account', level: 1 })).toBeVisible()
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    expect(asked.filter((url) => url.startsWith('/v1/account/')).sort()).toEqual(['/v1/account/history?broker=mock', '/v1/account/trades?limit=21&offset=0&broker=mock'])
  })
})
