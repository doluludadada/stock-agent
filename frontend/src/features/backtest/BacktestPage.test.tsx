import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { BacktestPage } from './BacktestPage'
import type { Backtest, BacktestInputs, BacktestSummary } from './model'

const LONGEST: BacktestInputs = { first: '2025-11-12', last: '2026-11-11', initial_cash: 1_000_000, buy_score: 80, sell_score: 40 }
const OPTIONS = { strategy_id: 'trend', strategy_name: 'Trend following', inputs: LONGEST }

const TRADED_ID = '11111111-1111-4111-8111-111111111111'
const IDLE_ID = '22222222-2222-4222-8222-222222222222'

const account = (equity: number) => ({ cash: equity, market_value: 0, unrealized_pnl: 0, equity, positions: [] })
const bar = (day: string, close: number) => ({ ts: `${day}T05:30:00Z`, open: close, high: close, low: close, close, volume: 0, change: null })

type Trade = Backtest['trades'][number]
const trade = (overrides: Partial<Trade>): Trade => ({
  stock_id: '2330',
  stock_name: '台積電',
  quantity: 1000,
  bought_on: '2026-05-05',
  average_cost: 100,
  sold_on: '2026-05-12',
  sold_at: 141,
  exit_source: 'combined',
  pnl: 40_500,
  fee: 300,
  tax: 400,
  held_sessions: 5,
  return_pct: 0.405,
  ...overrides,
})

const TRADED: Backtest = {
  backtest_id: TRADED_ID,
  created_at: '2026-11-12T02:00:00Z',
  strategy_id: 'trend',
  strategy_name: 'Trend following',
  inputs: { ...LONGEST, first: '2026-05-04', buy_score: 60 },
  stop_loss_pct: 0.08,
  risk_per_trade_pct: 0.02,
  first_session: '2026-05-04',
  last_session: '2026-11-11',
  final_equity: 1_032_000,
  total_return_pct: 0.032,
  benchmark_return_pct: 0.446,
  max_drawdown_pct: 0.051,
  trade_count: 3,
  winning_trades: 2,
  fee: 900,
  tax: 800,
  average_held_sessions: 12,
  equity_curve: { '2026-05-04': account(1_000_000), '2026-05-05': account(990_000), '2026-11-11': account(1_032_000) },
  benchmark: [bar('2026-05-04', 20_000), bar('2026-05-05', 21_000), bar('2026-11-11', 28_920)],
  trades: [
    trade({}),
    trade({ stock_id: '2317', stock_name: '鴻海', bought_on: '2026-05-08', sold_on: '2026-05-11', sold_at: 92, exit_source: 'stop_loss', pnl: -8_500, return_pct: -0.085, held_sessions: 1 }),
    trade({ stock_id: '2454', stock_name: '聯發科', bought_on: '2026-10-07', sold_on: null, sold_at: null, exit_source: null, pnl: 1_000, return_pct: 0.01, held_sessions: 30 }),
  ],
}

const IDLE: Backtest = {
  ...TRADED,
  backtest_id: IDLE_ID,
  created_at: '2026-11-12T03:00:00Z',
  inputs: LONGEST,
  first_session: '2025-11-12',
  final_equity: 1_000_000,
  total_return_pct: 0,
  max_drawdown_pct: 0,
  trade_count: 0,
  winning_trades: 0,
  fee: 0,
  tax: 0,
  average_held_sessions: null,
  equity_curve: { '2025-11-12': account(1_000_000), '2026-11-11': account(1_000_000) },
  benchmark: [bar('2025-11-12', 20_000), bar('2026-11-11', 28_920)],
  trades: [],
}

function summaryOf(backtest: Backtest): BacktestSummary {
  const { equity_curve: _days, benchmark: _bars, trades: _trades, ...summary } = backtest
  return summary
}

interface Site {
  options?: unknown
  saved?: Backtest[]
  /** What POST /v1/backtests answers; a promise holds the answer back the way a long replay does. */
  run?: () => Response | Promise<Response>
}

interface Call {
  method: string
  path: string
  body: unknown
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** The backtest endpoints as the backend answers them: a run is saved first in the list, and a delete removes one. */
function serve({ options = OPTIONS, saved = [], run }: Site = {}) {
  const calls: Call[] = []
  const store = [...saved]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const { pathname } = new URL(url, 'http://localhost')
      calls.push({ method, path: pathname, body: typeof init?.body === 'string' ? JSON.parse(init.body) : null })
      if (pathname === '/v1/backtests/options') return json(options)
      if (pathname === '/v1/backtests' && method === 'GET') return json(store.map(summaryOf))
      if (pathname === '/v1/backtests' && method === 'POST') {
        const answer = await (run ?? (() => json(TRADED)))()
        if (answer.ok) store.unshift((await answer.clone().json()) as Backtest)
        return answer
      }
      const [, id, action] = pathname.match(/^\/v1\/backtests\/([\w-]+)(\/delete)?$/) ?? []
      const index = store.findIndex((backtest) => backtest.backtest_id === id)
      if (index < 0) return json({ detail: `No saved backtest ${id}.`, code: 'not_found' }, 404)
      if (!action) return json(store[index])
      store.splice(index, 1)
      return new Response(null, { status: 204 })
    }),
  )
  return calls
}

function open(address = '/backtest', locale: 'en' | 'zh-TW' = 'en') {
  const i18n = initI18n('en')
  void i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={[address]}>
          <BacktestPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

const runs = (calls: Call[]) => calls.filter((call) => call.method === 'POST' && call.path === '/v1/backtests')

describe('the backtest page', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('starts the form from the options: the longest period, its cash and scores, on the active strategy', async () => {
    serve()
    open()

    expect(await screen.findByLabelText('From')).toHaveValue('2025-11-12')
    expect(screen.getByLabelText('To')).toHaveValue('2026-11-11')
    expect(screen.getByLabelText('Starting cash')).toHaveValue(1_000_000)
    expect(screen.getByLabelText('Buy score')).toHaveValue(80)
    expect(screen.getByLabelText('Sell score')).toHaveValue(40)
    expect(screen.getByText('Trend following')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Change strategy' })).toHaveAttribute('href', '/strategies')
    expect(screen.getByText('Daily history is available from 11/12/2025 to 11/11/2026.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Everything available' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('No backtest on screen')).toBeVisible()
    expect(screen.getByText(/^It decides on the technical score alone/)).toBeVisible()
  })

  it('runs the period, cash and scores typed, and leads with the answer against the index', async () => {
    const calls = serve()
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'Last 6 months' }))
    expect(screen.getByLabelText('From')).toHaveValue('2026-05-11')
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-05-04' } })
    await user.clear(screen.getByLabelText('Buy score'))
    await user.type(screen.getByLabelText('Buy score'), '60')
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))

    expect(await screen.findByTestId('verdict')).toHaveTextContent(
      'Over 05/04/2026 – 11/11/2026, this strategy would have made 32,000 (+3.20%). The TAIEX did +44.60% over the same sessions: the strategy is 41.4 points behind.',
    )
    expect(runs(calls).map((call) => call.body)).toEqual([{ confirm: true, inputs: { first: '2026-05-04', last: '2026-11-11', initial_cash: 1_000_000, buy_score: 60, sell_score: 40 } }])

    const stat = (label: string) => screen.getByText(label, { selector: 'dt' }).parentElement!
    expect(stat('Final equity')).toHaveTextContent('1,032,000')
    expect(stat('TAIEX')).toHaveTextContent('+44.60%')
    expect(stat('Max drawdown')).toHaveTextContent('-5.10%')
    expect(stat('Trades')).toHaveTextContent('32 won · 67%')
    expect(stat('Average held')).toHaveTextContent('12.0 sessions')
    expect(stat('Fees and tax')).toHaveTextContent('1,700')
    expect(stat('Buy / sell score')).toHaveTextContent('60 / 40')
    expect(stat('Buy / sell score')).toHaveTextContent('stop-loss 8.0% · risk 2.0% per trade')

    // The form keeps what was typed, ready for the next run.
    expect(screen.getByLabelText('Buy score')).toHaveValue(60)
    expect(screen.getByRole('button', { name: 'Run backtest' })).toBeEnabled()
    expect(await within(screen.getByRole('table', { name: 'Saved backtests' })).findAllByRole('row')).toHaveLength(2)
  })

  it('lists each trade with how it closed, and sorts them by P&L', async () => {
    serve({ saved: [TRADED] })
    const user = userEvent.setup()
    open(`/backtest?id=${TRADED_ID}`)

    const table = within(await screen.findByRole('table', { name: 'Trades' }))
    const stocks = () => table.getAllByRole('row').slice(1).map((row) => within(row).getByRole('link').getAttribute('href'))
    expect(stocks()).toEqual(['/stocks/2330', '/stocks/2317', '/stocks/2454'])

    const [won, stopped, held] = table.getAllByRole('row').slice(1)
    expect(won).toHaveTextContent('台積電')
    expect(won).toHaveTextContent('05/05/2026')
    expect(won).toHaveTextContent('100.00')
    expect(won).toHaveTextContent('05/12/2026')
    expect(won).toHaveTextContent('141.00')
    expect(won).toHaveTextContent('+40,500')
    expect(won).toHaveTextContent('+40.50%')
    expect(within(won!).getByText('Score')).toBeVisible()
    expect(within(stopped!).getByText('Stop-loss')).toBeVisible()
    expect(stopped).toHaveTextContent('-8,500')
    expect(within(held!).getAllByText('Still open').length).toBeGreaterThan(0)

    await user.click(table.getByRole('button', { name: 'Sort by P&L' }))
    expect(stocks()).toEqual(['/stocks/2330', '/stocks/2454', '/stocks/2317'])
    await user.click(table.getByRole('button', { name: 'Sort by P&L' }))
    expect(stocks()).toEqual(['/stocks/2317', '/stocks/2454', '/stocks/2330'])
    await user.click(table.getByRole('button', { name: 'Sort by Bought' }))
    expect(stocks()).toEqual(['/stocks/2454', '/stocks/2317', '/stocks/2330'])
  })

  it('says a backtest that bought nothing plainly, why, and what to try at the buy score', async () => {
    const calls = serve({ run: () => json(IDLE) })
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'Run backtest' }))

    expect(await screen.findByTestId('verdict')).toHaveTextContent('Over 11/12/2025 – 11/11/2026, this strategy bought nothing: the cash stayed at 1,000,000.')
    expect(screen.getByTestId('verdict')).toHaveTextContent('The TAIEX did +44.60% over the same sessions: the strategy is 44.6 points behind.')
    expect(screen.getByText('No trade is a result, not an error')).toBeVisible()
    expect(screen.getByText(/^No stock passed the strategy with a technical score of 80 or more/)).toBeVisible()
    expect(screen.getByText('The strategy bought nothing in this period.')).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Buy score')).toHaveAccessibleDescription(/^At 80 the backtest bought nothing\..*try a lower score\.$/)

    await user.click(screen.getByRole('button', { name: 'Set the buy score to 70' }))
    expect(screen.getByLabelText('Buy score')).toHaveValue(70)
    expect(runs(calls)).toHaveLength(1)
  })

  it('holds a period the server refuses at the period, with the days available, and keeps the form usable', async () => {
    const refusal = { detail: 'A backtest may cover 2025-11-12 to 2026-11-11.', code: 'backtest_period_unavailable' }
    const calls = serve({ run: () => json(refusal, 422) })
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'Run backtest' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('That period cannot be backtested. Choose days from 11/12/2025 to 11/11/2026 that hold at least one session.')
    expect(screen.getByRole('button', { name: 'Run backtest' })).toBeEnabled()
    expect(screen.getByLabelText('Buy score')).toHaveValue(80)
    await waitFor(() => expect(calls.filter((call) => call.path === '/v1/backtests/options')).toHaveLength(2))

    await user.click(screen.getByRole('button', { name: 'Last 3 months' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stops a period outside the days available before it asks the server', async () => {
    const calls = serve()
    const user = userEvent.setup()
    open()

    fireEvent.change(await screen.findByLabelText('From'), { target: { value: '2025-01-01' } })
    await user.clear(screen.getByLabelText('Sell score'))
    await user.click(screen.getByRole('button', { name: 'Run backtest' }))

    expect(screen.getByLabelText('From')).toHaveAccessibleDescription('The history starts on 11/12/2025.')
    expect(screen.getByLabelText('Sell score')).toHaveAccessibleDescription('Enter a whole number from 0 to 100.')
    expect(runs(calls)).toHaveLength(0)
  })

  it('shows a refused field in the server’s words at that field', async () => {
    const refusal = { detail: [{ loc: ['body', 'inputs', 'initial_cash'], msg: 'Input should be less than 1e12', type: 'less_than' }], code: 'invalid_request' }
    serve({ run: () => json(refusal, 422) })
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'Run backtest' }))
    await waitFor(() => expect(screen.getByLabelText('Starting cash')).toHaveAccessibleDescription('Input should be less than 1e12'))
  })

  it('counts the seconds of a long run, takes no second one meanwhile, and shows the result when it comes', async () => {
    let answer: (response: Response) => void = () => undefined
    const calls = serve({ run: () => new Promise<Response>((resolve) => (answer = resolve)) })
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'Run backtest' }))

    const progress = (await screen.findByText(/^Backtesting… \d+ s$/)).closest('output')
    expect(progress).toHaveTextContent('can take tens of seconds')
    expect(screen.getByRole('button', { name: 'Backtesting…' })).toBeDisabled()
    expect(screen.getByLabelText('Buy score')).toBeEnabled()

    await waitFor(() => expect(runs(calls)).toHaveLength(1))
    answer(json(TRADED))
    expect(await screen.findByTestId('verdict')).toBeVisible()
    expect(screen.queryByText(/^Backtesting…/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run backtest' })).toBeEnabled()
  })

  it('says a run failed on the page opened after it failed, when the page that started it was left meanwhile', async () => {
    let answer: (response: Response) => void = () => undefined
    serve({ run: () => new Promise<Response>((resolve) => (answer = resolve)) })
    const user = userEvent.setup()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const page = () =>
      render(
        <I18nextProvider i18n={initI18n('en')}>
          <QueryClientProvider client={client}>
            <MemoryRouter initialEntries={['/backtest']}>
              <BacktestPage />
            </MemoryRouter>
          </QueryClientProvider>
        </I18nextProvider>,
      )

    const first = page()
    await user.click(await screen.findByRole('button', { name: 'Run backtest' }))
    expect(await screen.findByRole('button', { name: 'Backtesting…' })).toBeDisabled()
    first.unmount()
    answer(json({ detail: 'boom' }, 500))
    await waitFor(() => expect(client.isMutating()).toBe(0))

    page()
    expect(await screen.findByRole('alert')).toHaveTextContent('The backtest did not run. The server could not finish this request.')
    expect(screen.getByRole('button', { name: 'Run backtest' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Last 3 months' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says the daily history is too short when the options name no period', async () => {
    serve({ options: { ...OPTIONS, inputs: null } })
    open()

    expect(await screen.findByText('Not enough daily history to backtest yet')).toBeVisible()
    expect(screen.getByText(/to replay Trend following\./)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Run backtest' })).not.toBeInTheDocument()
  })

  it('lists the saved backtests to compare, opens one, and fills the form with its settings on request', async () => {
    serve({ saved: [IDLE, TRADED] })
    const user = userEvent.setup()
    open()

    const table = within(await screen.findByRole('table', { name: 'Saved backtests' }))
    const [idle, traded] = table.getAllByRole('row').slice(1)
    expect(idle).toHaveTextContent('11/12/2025 – 11/11/2026')
    expect(idle).toHaveTextContent('80 / 40')
    expect(idle).toHaveTextContent('0.00%')
    expect(traded).toHaveTextContent('Trend following')
    expect(traded).toHaveTextContent('05/04/2026 – 11/11/2026')
    expect(traded).toHaveTextContent('60 / 40')
    expect(traded).toHaveTextContent('+3.20%')
    expect(traded).toHaveTextContent('+44.60%')

    const link = within(traded!).getByRole('link', { name: /^Open the backtest of 11\/12,? 10:00$/ })
    expect(link).toHaveAttribute('href', `/backtest?id=${TRADED_ID}`)
    await user.click(link)

    expect(await screen.findByTestId('verdict')).toHaveTextContent('would have made 32,000 (+3.20%)')
    expect(link).toHaveAttribute('aria-current', 'true')
    expect(screen.getByLabelText('Buy score')).toHaveValue(80)
    await user.click(screen.getByRole('button', { name: 'Use these settings' }))
    expect(screen.getByLabelText('Buy score')).toHaveValue(60)
    expect(screen.getByLabelText('From')).toHaveValue('2026-05-04')
  })

  it('deletes a saved backtest only after a yes, and closes its result', async () => {
    const calls = serve({ saved: [IDLE, TRADED] })
    const user = userEvent.setup()
    open(`/backtest?id=${TRADED_ID}`)

    expect(await screen.findByTestId('verdict')).toBeVisible()
    const deletes = () => calls.filter((call) => call.path.endsWith('/delete'))

    await user.click(screen.getByRole('button', { name: /^Delete the backtest of 11\/12,? 10:00$/ }))
    const dialog = within(await screen.findByRole('alertdialog'))
    expect(dialog.getByText(/Trend following, 05\/04\/2026 – 11\/11\/2026/)).toBeVisible()
    await user.click(dialog.getByRole('button', { name: 'Cancel' }))
    expect(deletes()).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: /^Delete the backtest of 11\/12,? 10:00$/ }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText('No backtest on screen')).toBeVisible()
    expect(deletes()).toEqual([{ method: 'POST', path: `/v1/backtests/${TRADED_ID}/delete`, body: { confirm: true } }])
    await waitFor(() => expect(within(screen.getByRole('table', { name: 'Saved backtests' })).getAllByRole('row')).toHaveLength(2))
    expect(screen.queryByTestId('verdict')).not.toBeInTheDocument()
  })

  it('says a saved backtest that is gone is gone', async () => {
    serve()
    const user = userEvent.setup()
    open(`/backtest?id=${TRADED_ID}`)

    expect(await screen.findByText('This backtest is no longer saved')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(await screen.findByText('No backtest on screen')).toBeVisible()
  })

  it('answers in Traditional Chinese', async () => {
    serve({ saved: [TRADED] })
    open(`/backtest?id=${TRADED_ID}`, 'zh-TW')

    expect(await screen.findByTestId('verdict')).toHaveTextContent(
      '2026/05/04 – 2026/11/11 這段期間，照這個策略操作會賺 32,000 元（+3.20%）。 同期加權指數 +44.60%，策略落後 41.4 個百分點。',
    )
    expect(screen.getByRole('button', { name: '開始回測' })).toBeEnabled()
  })
})
