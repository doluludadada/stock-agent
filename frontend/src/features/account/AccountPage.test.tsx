import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type Schemas } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { AccountPage } from './AccountPage'

type History = Schemas['AccountHistoryResponse']
type Trade = Schemas['TradeResponse']

const FULL_CYCLE = '11111111-1111-4111-8111-111111111111'
const FOLLOW_RUN = '22222222-2222-4222-8222-222222222222'
const INTRADAY = '33333333-3333-4333-8333-333333333333'

const unpriced = { stock_id: '2330', quantity: 1000, average_cost: 100, mark_price: 100, marked_at: null, market_value: 100_000, unrealized_pnl: 0 }
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
const SINOPAC_HISTORY: History = { ...HISTORY, execution_provider: 'shioaji', current: { ...value, cash: 405_000, equity: 505_000 }, opening: null, profit: null }

const MOCK = { broker: 'mock', simulation: null, max_order_value: null, max_daily_buy_value: null }
const SINOPAC = { broker: 'shioaji', simulation: true, max_order_value: 100_000, max_daily_buy_value: 300_000 }

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

/** The account endpoints and the listing, as the backend answers them; trades page by `limit` and `offset`. */
function serve(history: History, trades: Trade[], brokers: unknown[] = [MOCK]) {
  const asked: string[] = []
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      asked.push(url)
      const { pathname, searchParams } = new URL(url, 'http://localhost')
      if (pathname === '/v1/market/stocks') {
        const code = searchParams.get('query') ?? ''
        return json(LISTING[code] ? [{ stock_id: code, name: LISTING[code], market: 'twse', today: null }] : [])
      }
      if (pathname === '/v1/account/brokers') return json(brokers)
      if (pathname === '/v1/account/history') return json(searchParams.get('broker') === 'shioaji' ? SINOPAC_HISTORY : history)
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

  it('with no position and no trade, tells how to fill it: follow a finished analysis run', async () => {
    serve(EMPTY, [])
    open()

    expect(await screen.findByText('Nothing in your mock account yet')).toBeVisible()
    expect(screen.getByText(/^Open a finished analysis run and follow its decisions into this account\./)).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open the analysis runs' })).toHaveAttribute('href', '/runs')
    expect(screen.queryByRole('table', { name: 'Trades' })).not.toBeInTheDocument()
  })

  it('offers no other account while only the mock account is offered', async () => {
    serve(HISTORY, [])
    open()

    expect(await screen.findByText('1,012,000')).toBeVisible()
    expect(screen.queryByRole('radiogroup', { name: 'Account' })).not.toBeInTheDocument()
  })

  it('switches to the SinoPac account, asking its own history and trades, with no starting capital and no total P&L', async () => {
    const asked = serve(HISTORY, [], [MOCK, SINOPAC])
    const user = userEvent.setup()
    open()

    expect(await screen.findByText('1,012,000')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Mock account', level: 1 })).toBeVisible()
    await user.click(await screen.findByRole('radio', { name: 'SinoPac · simulation' }))

    expect(await screen.findByText('505,000')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'SinoPac account', level: 1 })).toBeVisible()
    expect(screen.queryByText('Total P&L')).not.toBeInTheDocument()
    expect(screen.queryByText('Starting capital')).not.toBeInTheDocument()
    expect(screen.getByText(/^SinoPac’s simulation server\./)).toBeVisible()
    expect(asked.filter((url) => url.includes('broker=shioaji')).sort()).toEqual(['/v1/account/history?broker=shioaji', '/v1/account/trades?limit=21&offset=0&broker=shioaji'])
  })
})
