import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { Toaster } from 'sonner'
import { initI18n } from '@/i18n'
import { session, type Order } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { CASH_FORMULA, SHIPPED_FORMULA } from '@/test/ranking'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import type { FormulaEvidence, Ranking, RankingBacktest, RankingFollow } from './model'
import { RankingPage } from './RankingPage'
import recordedBacktest from './test-support/backtest-2023-2024.json'
import recordedLatest from './test-support/latest.json'

/** What the backend answered on the real history; the recordings carry no stock names, so two are named here. */
const BACKTEST = recordedBacktest as RankingBacktest
const LATEST: Ranking = { ...(recordedLatest as Ranking), stocks: (recordedLatest as Ranking).stocks.map((stock, index) => (index < 2 ? { ...stock, stock_name: ['Alpha', 'Beta'][index]! } : stock)) }

/** The decision before the latest: it held 18 of the same stocks and two others. */
const BEFORE: Ranking = {
  ...LATEST,
  decided_on: '2026-09-14',
  revenue_month: '2026-08-01',
  stocks: [...LATEST.stocks.slice(2), { ...LATEST.stocks[0]!, stock_id: '1101', stock_name: 'Gamma' }, { ...LATEST.stocks[1]!, stock_id: '1102', stock_name: null }],
}
const LAST_TWO: RankingBacktest = { ...BACKTEST, first: '2026-09-01', last: '2026-10-13', rankings: [BEFORE, LATEST], holdings: {}, equity_curve: { '2026-09-14': 1, '2026-10-13': 1.1 }, benchmark_curve: { '2026-09-14': 1, '2026-10-13': 1.05 } }

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const refusal = (code: string, detail: string) => () => json({ detail, code }, 422)

const RECORD = {
  benchmark_id: '0050',
  annual_return: 0.583,
  benchmark_annual_return: 0.226,
  max_drawdown: 0.345,
  benchmark_max_drawdown: 0.34,
  years_ahead: 8,
  yearly_returns: Object.fromEntries(Array.from({ length: 10 }, (_, index) => [2017 + index, 0.1])),
  turnover: 0.686,
}
/** The shipped formula in use beside its cash variant, each as defined and at the comparison's floor. */
const EVIDENCE: FormulaEvidence[] = [
  { formula: SHIPPED_FORMULA, active: true, record: RECORD, liquid_floor: 200_000_000, liquid_record: { ...RECORD, annual_return: 0.418, max_drawdown: 0.379, years_ahead: 7, turnover: 0.62 } },
  {
    formula: CASH_FORMULA,
    active: false,
    record: { ...RECORD, annual_return: 0.41, max_drawdown: 0.298, years_ahead: 6, turnover: 0.553 },
    liquid_floor: 200_000_000,
    liquid_record: { ...RECORD, annual_return: 0.265, max_drawdown: 0.367, years_ahead: 5, turnover: 0.521 },
  },
]

interface Site {
  latest?: () => Response | Promise<Response>
  /** What a replay of a period other than the last two decisions answers. */
  backtest?: (first: string, last: string) => Response | Promise<Response>
  /** The mock account against the ranking; a second one is what the read after a follow started answers. */
  follow?: RankingFollow[]
  /** What the start of a follow answers. */
  start?: () => Response
}

const HOLDINGS = { decided_on: LATEST.decided_on, held: [], lacking: LATEST.stocks.map((stock) => stock.stock_id), left: [] }
const TIMES = ['09:05:00', '09:30:00', '10:00:00', '13:00:00']
const NEVER_FOLLOWED: RankingFollow = { holdings: HOLDINGS, refusal: null, running: false, performance: null, follows: [], schedule: { time: null, times: TIMES, broker: 'mock', broker_offered: true, brokers: ['mock'], pending: LATEST.decided_on, unfinished: null, due: false } }
/** A month after the first follow: 18 of the 20 held, the two that entered lacking and one that left still held. */
const A_MONTH_IN: RankingFollow = {
  holdings: { ...HOLDINGS, held: HOLDINGS.lacking.slice(2), lacking: HOLDINGS.lacking.slice(0, 2), left: ['1101'] },
  refusal: null,
  running: false,
  performance: { since: '2026-09-15', until: '2026-10-13', account_return: 0.0312, benchmark_id: '0050', benchmark_return: 0.021 },
  follows: [
    { run_id: '00000000-0000-0000-0000-000000000011', start_time: '2026-09-15T01:05:00Z', ranking_formula: SHIPPED_FORMULA, ranking_decided_on: '2026-09-14', scheduled: false, execution_provider: 'mock' },
    { run_id: '00000000-0000-0000-0000-000000000012', start_time: '2026-10-14T01:05:00Z', ranking_formula: CASH_FORMULA, ranking_decided_on: '2026-10-13', scheduled: true, execution_provider: 'mock' },
  ],
  schedule: { time: '09:05:00', times: TIMES, broker: 'mock', broker_offered: true, brokers: ['mock'], pending: null, unfinished: null, due: false },
}

/** A follow on SinoPac's simulation account, which the site offers this user, and the orders its run placed there. */
const SINOPAC_RUN = '00000000-0000-0000-0000-000000000021'
const ON_SINOPAC: RankingFollow = {
  ...A_MONTH_IN,
  follows: [...A_MONTH_IN.follows, { ...A_MONTH_IN.follows[1]!, run_id: SINOPAC_RUN, start_time: '2026-11-10T01:05:00Z', scheduled: false, execution_provider: 'shioaji' }],
  schedule: { ...A_MONTH_IN.schedule, brokers: ['mock', 'shioaji'] },
}
const order = (stockId: string, action: Order['action'], status: Order['status'], filled: number, reason: string | null = null): Order => ({
  id: `order-${stockId}`,
  run_id: SINOPAC_RUN,
  decision_id: `decision-${stockId}`,
  stock_id: stockId,
  action,
  order_type: 'limit',
  quantity: 1000,
  limit_price: 512,
  time_in_force: 'rod',
  status,
  reason,
  filled_quantity: filled,
  average_filled_price: filled > 0 ? 512 : null,
  fee: 0,
  tax: 0,
  realized_pnl: null,
  created_at: '2026-11-10T01:05:00Z',
  updated_at: '2026-11-10T01:05:00Z',
})
const SINOPAC_ORDERS = [order('2330', 'buy', 'filled', 1000), order('2317', 'buy', 'submitted', 0), order('1101', 'sell', 'rejected', 0, 'The broker refused the order.')]

/** The ranking endpoints as the backend answers them; returns the replays asked, each as `first..last`. */
function serve({ latest = () => json(LATEST), backtest = () => json(BACKTEST), follow = [NEVER_FOLLOWED], start = () => json({ run_id: '00000000-0000-0000-0000-000000000001' }, 202) }: Site = {}) {
  const asked: string[] = []
  const answers = [...follow]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const { pathname, searchParams } = new URL(url, 'http://localhost')
      if (pathname === '/v1/market/audience') return json(PERSONAL_SITE)
      if (pathname === '/v1/rankings/follow') {
        asked.push(`${init?.method ?? 'GET'} follow${searchParams.size > 0 ? `?${searchParams}` : ''}`)
        return init?.method === 'POST' ? start() : json(answers.length > 1 ? answers.shift() : answers[0])
      }
      const ordersOf = pathname.match(/^\/v1\/runs\/([\w-]+)\/orders$/)?.[1]
      if (ordersOf) {
        asked.push('orders')
        return json(ordersOf === SINOPAC_RUN ? SINOPAC_ORDERS : [])
      }
      if (pathname === '/v1/rankings/latest') {
        asked.push('latest')
        return latest()
      }
      if (pathname === '/v1/rankings/formulas') {
        asked.push(`formulas ${searchParams.get('first')}..${searchParams.get('last')}`)
        return json(EVIDENCE)
      }
      if (pathname === '/v1/rankings/backtest') {
        const [first, last] = [searchParams.get('first')!, searchParams.get('last')!]
        asked.push(`${first}..${last}`)
        return first === '2026-09-01' ? json(LAST_TWO) : backtest(first, last)
      }
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  return asked
}

/** Opens what is one tap from the backtest's figures: the period, the curve, every year, every decision and the caveats. */
async function openDetail() {
  await userEvent.click(await screen.findByRole('button', { name: 'Period, chart and every decision' }))
}

function open(address = '/ranking', locale: 'en' | 'zh-TW' = 'en', mockAccount = false) {
  const i18n = initI18n('en')
  void i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={[address]}>
          <RankingPage mockAccount={mockAccount} />
          <Toaster />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the ranking page', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-12T03:00:00Z'))
    session.signIn(TEST_USER)
  })
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('leads with the stocks picked now: the decision, the revenue read, when the next one is due, and both factors in words', async () => {
    serve()
    open()

    const table = await screen.findByRole('table', { name: "This month's ranking" })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(20)
    expect(within(rows[0]!).getByRole('link', { name: /Alpha/ })).toHaveAttribute('href', '/stocks/3311')
    expect(rows[0]).toHaveTextContent('2.09×')
    expect(rows[0]).toHaveTextContent('At its high')
    expect(rows[0]).toHaveTextContent('beats 99.6%')
    expect(rows[10]).toHaveTextContent(/[-−]2\.1%/)
    expect(within(rows[2]!).getByRole('link', { name: /6834/ })).toHaveAttribute('href', '/stocks/6834')

    expect(screen.getByText('10/13/2026 · September 2026 revenue')).toBeVisible()
    expect(screen.getByText('Next decision about 11/13')).toBeVisible()
    expect(screen.getByText('For research and reference only, not investment advice.')).toBeVisible()
  })

  it('puts the list first, then the backtest as three figures marked simulated, with the detail closed until asked for', async () => {
    serve()
    open()

    const compared = await screen.findByRole('table', { name: 'The ranking against 0050' })
    expect(screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)).toEqual(["This month's ranking", 'BacktestSimulated', 'Formulas comparedSimulated'])
    expect(within(compared).getAllByRole('row').slice(1)).toHaveLength(3)
    expect(screen.getByText('01/13/2023 to 10/30/2024')).toBeVisible()
    for (const name of ['Every year', 'Backtest: every past decision']) expect(screen.queryByRole('table', { name })).not.toBeInTheDocument()
    expect(screen.queryByText('This is a backtest, not a track record.')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Last 3 years' })).not.toBeInTheDocument()

    await openDetail()
    expect(screen.getByRole('table', { name: 'Every year' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Last 3 years' })).toBeVisible()
  })

  it('names the formula at the list and the backtest, with its factors as the list’s columns', async () => {
    serve()
    open()

    const table = await screen.findByRole('table', { name: "This month's ranking" })
    expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['Place', 'Stock', 'Price', 'Revenue, 3 mo ÷ 12 mo', 'Vs 250-session high', 'Score'])
    await screen.findByRole('table', { name: 'The ranking against 0050' })
    expect(screen.getAllByText('Revenue, 3 mo ÷ 12 mo + Vs 250-session high').length).toBeGreaterThanOrEqual(2)
  })

  it('says plainly that the formula holds cash where the list would be, and still when the next decision is due', async () => {
    serve({ latest: () => json({ ...LATEST, formula: CASH_FORMULA, holds_cash: true, stocks: [] }) })
    open()

    expect(await screen.findByText('The formula holds cash this month')).toBeVisible()
    expect(screen.getByText(`The benchmark closed under its 60-session average at the decision, so it holds no stock until the next one. ${LATEST.scored} stocks still have a score.`)).toBeVisible()
    expect(screen.getByText('Revenue, 3 mo ÷ 12 mo + Vs 250-session high · Cash while the benchmark is under its 60-session average')).toBeVisible()
    expect(screen.queryByRole('table', { name: "This month's ranking" })).not.toBeInTheDocument()
    expect(screen.queryByText('Nothing could be ranked this month')).not.toBeInTheDocument()
    expect(screen.getByText('Next decision about 11/13')).toBeVisible()
  })

  it('compares every formula over the backtest’s period, as defined and at the liquidity floor, and marks the one in use', async () => {
    const asked = serve()
    open()

    const table = await screen.findByRole('table', { name: 'Formulas compared' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => row.textContent)).toEqual([
      'Revenue, 3 mo ÷ 12 mo + Vs 250-session highIn useahead 8 of 10 years · buys 69% a month+58.3%-34.5%8 of 1069%',
      'Only stocks trading NT$200M a day · ahead 7 of 10 years · buys 62% a month+41.8%-37.9%7 of 1062%',
      'Revenue, 3 mo ÷ 12 mo + Vs 250-session high · Cash while the benchmark is under its 60-session averageahead 6 of 10 years · buys 55% a month+41.0%-29.8%6 of 1055%',
      'Only stocks trading NT$200M a day · ahead 5 of 10 years · buys 52% a month+26.5%-36.7%5 of 1052%',
    ])
    expect(screen.getByText('0050 over the same sessions: +22.6% a year, deepest fall -34.0%. The formula that did best over a past period is not thereby the best next.')).toBeVisible()
    expect(asked.filter((request) => request.startsWith('formulas'))).toEqual(['formulas 2000-01-01..2026-11-12'])
    expect(asked.indexOf('formulas 2000-01-01..2026-11-12')).toBeGreaterThan(asked.indexOf('2000-01-01..2026-11-12'))
  })

  it('lists the formula each follow of the mock account used, newest first', async () => {
    serve({ follow: [A_MONTH_IN] })
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    const follows = within(await within(block).findByRole('list', { name: 'Followed with' })).getAllByRole('listitem')
    expect(follows.map((item) => item.textContent)).toEqual([
      '10/14/2026 schedule · Mock account · Revenue, 3 mo ÷ 12 mo + Vs 250-session high · Cash while the benchmark is under its 60-session average Orders of 10/14 Run log of 10/14',
      '09/15/2026 by hand · Mock account · Revenue, 3 mo ÷ 12 mo + Vs 250-session high Orders of 9/15 Run log of 9/15',
    ])
    expect(within(block).getByTestId('follow-schedule')).toHaveTextContent('Schedule on: next follow about 11/16 09:05. Last followed 10/14 by the schedule. Change')
    expect(within(block).getByRole('link', { name: 'Change' })).toHaveAttribute('href', '/settings')
  })

  it('says the account each follow ran on, and gives each its orders, with the status the broker gave each, and its run', async () => {
    const asked = serve({ follow: [ON_SINOPAC] })
    const user = userEvent.setup()
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    const follows = within(await within(block).findByRole('list', { name: 'Followed with' })).getAllByRole('listitem')
    expect(follows.map((item) => item.textContent?.replace(/ · Revenue.*/, ''))).toEqual(['11/10/2026 by hand · SinoPac (simulation)', '10/14/2026 schedule · Mock account', '09/15/2026 by hand · Mock account'])
    expect(follows.map((item) => within(item).getByRole('button').textContent)).toEqual(['Orders of 11/10', 'Orders of 10/14', 'Orders of 9/15'])
    expect(follows.map((item) => within(item).getByRole('link').getAttribute('href')), 'the run’s log says what a follow left for a later one').toEqual([
      `/runs/${SINOPAC_RUN}`,
      `/runs/${A_MONTH_IN.follows[1]!.run_id}`,
      `/runs/${A_MONTH_IN.follows[0]!.run_id}`,
    ])
    expect(within(follows[0]!).getByRole('link')).toHaveAccessibleName('Run log of 11/10')
    expect(asked, 'the orders wait for the reader').not.toContain('orders')

    await user.click(within(follows[0]!).getByRole('button', { name: 'Orders of 11/10' }))
    const rows = within(await within(block).findByRole('table', { name: 'Orders of 11/10' })).getAllByRole('row')
    expect(rows.slice(1).map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent))).toEqual([
      ['2330', 'BUY', 'Filled', '1,000 / 1,000'],
      ['2317', 'BUY', 'Submitted', '0 / 1,000'],
      ['1101', 'SELL', 'RejectedThe broker refused the order.', '0 / 1,000'],
    ])

    await user.click(within(follows[0]!).getByRole('button', { name: 'Orders of 11/10' }))
    expect(within(block).queryByRole('table', { name: 'Orders of 11/10' })).not.toBeInTheDocument()
  })

  it('offers a follow on SinoPac’s simulation account only where the site offers it, and starts it there after a yes that says no real money moves', async () => {
    serve({ follow: [A_MONTH_IN] })
    open('/ranking', 'en', true)
    const mockOnly = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(mockOnly).findByRole('button', { name: 'Follow this month’s ranking' })).toBeEnabled()
    expect(within(mockOnly).queryByRole('button', { name: 'Follow on SinoPac (simulation)' })).not.toBeInTheDocument()
    cleanup()

    const asked = serve({ follow: [ON_SINOPAC, { ...ON_SINOPAC, running: true }] })
    const user = userEvent.setup()
    open('/ranking', 'en', true)
    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByText(/Its orders go to SinoPac’s simulation server; no real money is used\./)).toBeVisible()
    await user.click(within(block).getByRole('button', { name: 'Follow on SinoPac (simulation)' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Bring SinoPac’s simulation account to this month’s ranking?' })
    expect(within(dialog).getByText(/at a realtime quote now\. The orders go to SinoPac’s simulation server; no real money moves\./)).toBeVisible()
    expect(asked.filter((request) => request.startsWith('POST'))).toEqual([])

    await user.click(within(dialog).getByRole('button', { name: 'Follow' }))
    await waitFor(() => expect(within(block).getByRole('button', { name: 'Follow on SinoPac (simulation)' })).toBeDisabled())
    expect(asked.filter((request) => request.startsWith('POST'))).toEqual(['POST follow?broker=shioaji'])
  })

  it('leaves the SinoPac follow to the server’s answer, whatever the mock account’s own refusal says', async () => {
    const held = { ...A_MONTH_IN.holdings, held: HOLDINGS.lacking, lacking: [], left: [] }
    const asked = serve({ follow: [{ ...ON_SINOPAC, refusal: 'outside_follow_window' }], start: () => json({ detail: 'Outside the window.', code: 'outside_follow_window' }, 409) })
    const user = userEvent.setup()
    open('/ranking', 'en', true)
    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByRole('button', { name: 'Follow this month’s ranking' })).toBeDisabled()
    const sinopac = within(block).getByRole('button', { name: 'Follow on SinoPac (simulation)' })
    expect(sinopac).toBeEnabled()
    await user.click(sinopac)
    const dialog = await screen.findByRole('alertdialog', { name: 'Bring SinoPac’s simulation account to this month’s ranking?' })
    expect(within(dialog).getByText(/^BUYs are paid from the cash the account has now; what this follow sells counts once it settles, so some BUYs may wait for a later follow/)).toBeVisible()
    await user.click(within(dialog).getByRole('button', { name: 'Follow' }))
    expect(await screen.findByText('This site places no order now. Follow the run when its window opens.')).toBeVisible()
    expect(asked.filter((request) => request.startsWith('POST'))).toEqual(['POST follow?broker=shioaji'])
    cleanup()

    serve({ follow: [{ ...ON_SINOPAC, holdings: held, refusal: 'nothing_to_follow' }], start: () => json({ detail: 'Nothing to follow.', code: 'nothing_to_follow' }, 409) })
    open('/ranking', 'en', true)
    const upToDate = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    await user.click(await within(upToDate).findByRole('button', { name: 'Follow on SinoPac (simulation)' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Follow' }))
    expect(await screen.findByText('SinoPac’s simulation account holds this month’s ranking.')).toBeVisible()
  })

  it('says why SinoPac refused a follow, and that a schedule on SinoPac follows there or on no account', async () => {
    serve({ follow: [{ ...ON_SINOPAC, schedule: { ...ON_SINOPAC.schedule, broker: 'shioaji' } }], start: () => json({ detail: 'Not the simulation server.', code: 'not_simulation' }, 403) })
    const user = userEvent.setup()
    open('/ranking', 'en', true)
    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByTestId('follow-schedule')).toHaveTextContent('Schedule on: next follow about 11/16 09:05. It follows on SinoPac’s simulation account. Last followed 11/10 by hand. Change')
    await user.click(within(block).getByRole('button', { name: 'Follow on SinoPac (simulation)' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Follow' }))
    expect(await screen.findByText(/The site’s SinoPac login is not on the simulation server, and a ranking follow never orders with real money\./)).toBeVisible()
    cleanup()

    serve({ follow: [{ ...A_MONTH_IN, schedule: { ...A_MONTH_IN.schedule, broker: 'shioaji', broker_offered: false } }] })
    open('/ranking', 'zh-TW', true)
    expect(await screen.findByTestId('follow-schedule')).toHaveTextContent('排程開啟：下次跟單約在 11/16 09:05。 本站目前不會幫你在永豐金模擬帳戶跟單，也不會改在其他帳戶跟單。 上次跟單 10/14，由排程執行。')
    cleanup()

    serve({ follow: [ON_SINOPAC] })
    open('/ranking', 'en', true)
    expect(await screen.findByTestId('follow-schedule')).toHaveTextContent('Schedule on: next follow about 11/16 09:05. It follows on your mock account. Last followed 11/10 by hand. Change')
  })

  it('says the schedule is off, and which decision a schedule that is on still has to follow', async () => {
    serve({ follow: [NEVER_FOLLOWED] })
    open('/ranking', 'en', true)
    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByTestId('follow-schedule')).toHaveTextContent('Schedule off. Change')
    cleanup()

    serve({ follow: [{ ...NEVER_FOLLOWED, schedule: { ...NEVER_FOLLOWED.schedule, time: '09:30:00' } }] })
    open('/ranking', 'en', true)
    const pending = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(pending).findByTestId('follow-schedule')).toHaveTextContent('Schedule on: follows the 10/13 decision on the next trading day from 09:30. Change')
  })

  it('says a scheduled follow that did not finish, why, and that it tries again, with the run one tap away', async () => {
    const tried = { run_id: '00000000-0000-0000-0000-000000000013', start_time: '2026-11-11T01:05:00Z', end_time: '2026-11-11T01:06:00Z', failure: null, ranking_open: 2 }
    const partial = { ...A_MONTH_IN.follows[1]!, run_id: tried.run_id, start_time: tried.start_time }
    const stuck: RankingFollow = { ...A_MONTH_IN, follows: [...A_MONTH_IN.follows, partial], schedule: { ...A_MONTH_IN.schedule, pending: LATEST.decided_on, unfinished: tried } }
    serve({ follow: [stuck] })
    open('/ranking', 'en', true)
    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    const line = await within(block).findByTestId('follow-schedule')
    expect(line).toHaveTextContent(
      'Schedule on. Its follow on 11/11 did not finish: 2 stocks were left to trade, as an order was refused or did not fill, or the cash was short of one lot. It tries again on the next trading day from 09:05. See the run Last followed 10/14 by the schedule. Change',
    )
    expect(within(line).getByRole('link', { name: 'See the run' })).toHaveAttribute('href', `/runs/${tried.run_id}`)
    cleanup()

    serve({ follow: [{ ...stuck, follows: A_MONTH_IN.follows, schedule: { ...stuck.schedule, unfinished: { ...tried, ranking_open: null } } }] })
    open('/ranking', 'zh-TW', true)
    expect(await screen.findByTestId('follow-schedule')).toHaveTextContent('排程開啟。11/11 的跟單沒有跟完：當時無法開始，因為不在交易時段，或排名沒有排出任何股票。下一個交易日 09:05 起會再試。 查看那次執行')
  })

  it('keeps the unfinished follow to itself while a follow runs, and while the schedule is off', async () => {
    const tried = { run_id: '00000000-0000-0000-0000-000000000013', start_time: '2026-11-11T01:05:00Z', end_time: null, failure: null, ranking_open: null }
    const schedule = { ...NEVER_FOLLOWED.schedule, time: '09:30:00', unfinished: tried }
    serve({ follow: [{ ...NEVER_FOLLOWED, running: true, schedule }] })
    open('/ranking', 'en', true)
    expect(await screen.findByTestId('follow-schedule')).toHaveTextContent('Schedule on: follows the 10/13 decision on the next trading day from 09:30. Change')
    cleanup()

    serve({ follow: [{ ...NEVER_FOLLOWED, schedule: { ...schedule, time: null } }] })
    open('/ranking', 'en', true)
    expect(await screen.findByTestId('follow-schedule')).toHaveTextContent('Schedule off. Change')
  })

  it('offers a follow to cash that lists only sales while the formula holds cash', async () => {
    const cash = { ...LATEST, formula: CASH_FORMULA, holds_cash: true, stocks: [] }
    serve({ latest: () => json(cash), follow: [{ ...NEVER_FOLLOWED, holdings: { decided_on: LATEST.decided_on, held: [], lacking: [], left: ['1101', '2317'] } }] })
    const user = userEvent.setup()
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByText('The formula holds cash now. To follow: sell 2.')).toBeVisible()
    await user.click(within(block).getByRole('button', { name: 'Follow this month’s ranking' }))
    const listed = within(await screen.findByRole('alertdialog')).getAllByRole('listitem').map((item) => item.textContent)
    expect(listed).toEqual(['1101 SELL', '2317 SELL'])
  })

  it('asks nothing about the mock account where the site does not show it', async () => {
    const asked = serve()
    open()

    await screen.findByRole('table', { name: 'The ranking against 0050' })
    expect(screen.queryByRole('region', { name: 'The ranking in your mock account' })).not.toBeInTheDocument()
    expect(asked.filter((request) => request.endsWith('follow'))).toEqual([])
  })

  it('says that the mock account does not follow yet, and follows the ranking after a yes that lists every order', async () => {
    const asked = serve({ follow: [NEVER_FOLLOWED, { ...NEVER_FOLLOWED, running: true }] })
    const user = userEvent.setup()
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByText('Not followed yet.')).toBeVisible()
    expect(within(block).getByRole('link', { name: 'Mock account' })).toHaveAttribute('href', '/account')
    expect(within(block).queryByText('Holds')).not.toBeInTheDocument()

    await user.click(within(block).getByRole('button', { name: 'Follow this month’s ranking' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Bring your mock account to this month’s ranking?' })
    const listed = within(dialog).getAllByRole('listitem').map((item) => item.textContent)
    expect(listed).toHaveLength(20)
    expect(listed.slice(0, 2)).toEqual([`${LATEST.stocks[0]!.stock_id} AlphaBUY`, `${LATEST.stocks[1]!.stock_id} BetaBUY`])
    expect(within(dialog).getByText(/at a realtime quote now\. Only your mock account changes; no real money moves\./)).toBeVisible()
    expect(asked.filter((request) => request.startsWith('POST'))).toEqual([])

    await user.click(within(dialog).getByRole('button', { name: 'Follow' }))
    expect(await within(block).findByText('A run is in progress…')).toBeVisible()
    expect(within(block).getByRole('button', { name: 'Follow this month’s ranking' })).toBeDisabled()
    expect(asked.filter((request) => request.startsWith('POST'))).toEqual(['POST follow?broker=mock'])
  })

  it('says what the mock account holds of the ranking and what it made since its first follow against the benchmark', async () => {
    serve({ follow: [A_MONTH_IN] })
    const user = userEvent.setup()
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByText('18 of 20')).toBeVisible()
    expect(block).toHaveTextContent('Since 9/15Up +3.12%0050Up +2.10%')
    expect(block).toHaveTextContent(`Lacks: ${A_MONTH_IN.holdings.lacking.join(' ')}`)
    expect(block).toHaveTextContent('Left the ranking, still held: 1101')
    expect(within(block).getByText('To catch up: sell 1, buy 2.')).toBeVisible()

    await user.click(within(block).getByRole('button', { name: 'Follow this month’s ranking' }))
    const listed = within(await screen.findByRole('alertdialog')).getAllByRole('listitem').map((item) => item.textContent)
    expect(listed).toEqual(['1101 SELL', `${LATEST.stocks[0]!.stock_id} AlphaBUY`, `${LATEST.stocks[1]!.stock_id} BetaBUY`])
  })

  it('offers no follow once the mock account holds the ranking, and says why one cannot start outside the window', async () => {
    const held = { ...A_MONTH_IN.holdings, held: HOLDINGS.lacking, lacking: [], left: [] }
    serve({ follow: [{ ...A_MONTH_IN, holdings: held, refusal: 'nothing_to_follow' }] })
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByText('20 of 20')).toBeVisible()
    expect(block, 'the figures say it; no sentence repeats them').not.toHaveTextContent(/holds this month/)
    expect(within(block).queryByRole('button', { name: 'Follow this month’s ranking' })).not.toBeInTheDocument()
    cleanup()

    serve({ follow: [{ ...A_MONTH_IN, holdings: held, refusal: 'nothing_to_follow', performance: null }] })
    open('/ranking', 'en', true)
    const unmeasured = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(unmeasured).findByText('20 of 20'), 'an account that holds the ranking with no return to measure yet').toBeVisible()
    expect(unmeasured).not.toHaveTextContent(/ranks no stock|0050/)
    cleanup()

    serve({ follow: [{ ...NEVER_FOLLOWED, refusal: 'outside_follow_window' }] })
    open('/ranking', 'en', true)
    expect(await screen.findByText(/^Not now\. This site follows at a realtime quote, so only in continuous trading/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Follow this month’s ranking' })).toBeDisabled()
  })

  it('says the next decision should be here once its day has come', async () => {
    vi.setSystemTime(new Date('2026-11-16T03:00:00Z'))
    serve()
    open()

    expect(await screen.findByText('The next decision is due')).toBeVisible()
  })

  it('marks the stocks that entered since the decision before and lists the ones that left', async () => {
    serve()
    open()

    const changed = await screen.findByRole('button', { name: '2 new · 2 left' })
    expect(changed).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(changed)
    const left = screen.getByRole('list', { name: 'Left the ranking' })
    expect(within(left).getByRole('link', { name: /Gamma/ })).toHaveAttribute('href', '/stocks/1101')
    expect(within(left).getByRole('link', { name: '1102' })).toHaveAttribute('href', '/stocks/1102')
    const rows = within(screen.getByRole('table', { name: "This month's ranking" })).getAllByRole('row').slice(1)
    expect(rows.filter((row) => within(row).queryByText('New'))).toHaveLength(2)
    expect(within(rows[0]!).getByText('New')).toBeVisible()
  })

  it('answers whether following it beat the benchmark: both sides of each figure, then every year and the costs in the detail', async () => {
    const asked = serve()
    open()

    const compared = await screen.findByRole('table', { name: 'The ranking against 0050' })
    expect(within(compared).getByRole('row', { name: /A year, on average/ })).toHaveTextContent('+79.6%+37.5%')
    expect(within(compared).getByRole('row', { name: /1 put in became/ })).toHaveTextContent('2.81.7')
    expect(within(compared).getByRole('row', { name: /Deepest fall/ })).toHaveTextContent(/[-−]16\.6%[-−]21\.3%/)
    await openDetail()
    expect(screen.getByText(/about 9\.6% of the assets over the period \(fee 0\.1425%, tax on a sale 0\.3%\)/)).toBeVisible()

    const years = screen.getByRole('table', { name: 'Every year' })
    expect(within(years).getByRole('row', { name: /2024/ })).toHaveTextContent('to 10/30')
    expect(within(years).getByRole('row', { name: /2024/ })).toHaveTextContent('Up +81.0%Up +45.6%+35.3 points')
    expect(within(years).getByRole('row', { name: /2023/ })).toHaveTextContent('from 1/13')

    expect(asked[0]).toBe('latest')
    expect(asked.slice(1).filter((request) => !request.startsWith('formulas')).sort()).toEqual(['2000-01-01..2026-11-12', '2026-09-01..2026-10-13'])
  })

  it('marks a year the ranking lost money in and one it fell behind the benchmark in', async () => {
    serve({
      backtest: () =>
        json({ ...BACKTEST, yearly_returns: { 2023: -0.25, 2024: 0.1 }, benchmark_yearly_returns: { 2023: -0.21, 2024: 0.2 }, annual_return: 0.1, benchmark_annual_return: 0.2 }),
    })
    open()

    await openDetail()
    const years = await screen.findByRole('table', { name: 'Every year' })
    expect(within(years).getByRole('row', { name: /2023/ })).toHaveTextContent('Lost money')
    expect(within(years).getByRole('row', { name: /2023/ })).toHaveTextContent('Behind 0050')
    expect(within(years).getByRole('row', { name: /2024/ })).not.toHaveTextContent('Lost money')
    expect(within(years).getByRole('row', { name: /2024/ })).toHaveTextContent('Behind 0050')
    expect(screen.getByText('2 years · 1 lost money · 2 behind the benchmark')).toBeVisible()
  })

  it('says each measured caveat in the backtest’s detail', async () => {
    serve()
    open()

    await openDetail()
    expect(await screen.findByText('This is a backtest, not a track record.')).toBeVisible()
    expect(screen.getByText(/In 2018, 40 of the 521 liquid stocks had no revenue data, and 37 of them later delisted\./)).toBeVisible()
    expect(screen.getByText('Every formula here was picked from many tried.')).toBeVisible()
    expect(screen.getByText(/The deepest fall above happened once and can happen again\./)).toBeVisible()
    expect(screen.getByText('Buying a few days late cut the result sharply.')).toBeVisible()
  })

  it('asks for a quick period once, and for two typed days only when they are applied', async () => {
    const asked = serve()
    open()
    await openDetail()
    const replays = () => asked.filter((item) => item !== 'latest' && !item.startsWith('2026-09-01') && !item.startsWith('formulas'))
    expect(replays()).toEqual(['2000-01-01..2026-11-12'])
    expect(screen.getByRole('button', { name: 'Whole history' })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(screen.getByRole('button', { name: 'Last 3 years' }))
    await waitFor(() => expect(replays()).toEqual(['2000-01-01..2026-11-12', '2023-11-12..2026-11-12']))
    expect(screen.getByRole('button', { name: 'Last 3 years' })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(screen.getByRole('button', { name: 'Custom' }))
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2023-01-01' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2022-10-31' } })
    expect(replays()).toHaveLength(2)

    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByText('The end is before the start.')).toBeVisible()
    expect(replays()).toHaveLength(2)

    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2024-10-31' } })
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => expect(replays()).toEqual(['2000-01-01..2026-11-12', '2023-11-12..2026-11-12', '2023-01-01..2024-10-31']))
    expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(screen.getByRole('button', { name: 'Whole history' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Whole history' })).toHaveAttribute('aria-pressed', 'true'))
    expect(replays()).toHaveLength(3)
  })

  it('lists every past decision with how holding it went, each a link that opens it', async () => {
    serve()
    open()

    await openDetail()
    const months = await screen.findByRole('table', { name: 'Backtest: every past decision' })
    expect(within(months).getAllByRole('row').slice(1)).toHaveLength(12)
    expect(within(months).getByRole('link', { name: 'Open the ranking of 09/13/2024' })).toHaveAttribute('href', '/ranking?month=2024-09-13')
    await userEvent.click(screen.getByRole('button', { name: 'Show all 22 decisions' }))
    expect(within(months).getAllByRole('row').slice(1)).toHaveLength(22)
    expect(within(months).getAllByRole('row')[1]).toHaveTextContent(/10\/14\/2024Held now/)

    await userEvent.click(within(months).getByRole('link', { name: 'Open the ranking of 09/13/2024' }))
    expect(await screen.findByRole('dialog', { name: 'The ranking of 09/13/2024' })).toBeVisible()
  })

  it('opens the decision the address names: what it read, when it bought, and a stock it could not sell', async () => {
    serve()
    open('/ranking?month=2024-10-14')

    const dialog = await screen.findByRole('dialog', { name: 'The ranking of 10/14/2024' })
    expect(dialog).toHaveTextContent('It read the revenue of September 2024. Bought at the open of 10/15/2024; counted to the close of 10/30/2024 so far.')
    expect(within(dialog).getAllByRole('row').slice(1)).toHaveLength(20)
    expect(within(dialog).getByText(/could not be sold/)).toBeVisible()
    expect(within(dialog).getByRole('link', { name: '8249' })).toHaveAttribute('href', '/stocks/8249')
    expect(within(dialog).getByRole('link', { name: /Decision before/ })).toHaveAttribute('href', '/ranking?month=2024-09-13')
  })

  it('marks a ranked stock that could not be bought in its month', async () => {
    serve()
    open('/ranking?month=2023-02-13')

    const dialog = await screen.findByRole('dialog', { name: 'The ranking of 02/13/2023' })
    expect(within(dialog).getAllByText('Not bought')).toHaveLength(1)
    expect(dialog).toHaveTextContent('Bought at the open of 02/14/2023 and held to the close of 03/13/2023.')
  })

  it('counts the seconds while the first answer is computed and asks for no replay meanwhile', async () => {
    let answer!: (response: Response) => void
    const asked = serve({ latest: () => new Promise((resolve) => (answer = resolve)) })
    open()

    expect(await screen.findByText(/^Computing… \d+ s$/)).toBeVisible()
    expect(screen.getByText(/The first answer after a start takes about a minute/)).toBeVisible()
    expect(asked).toEqual(['latest'])

    answer(json(LATEST))
    expect(await screen.findByRole('table', { name: "This month's ranking" })).toBeVisible()
    await screen.findByRole('table', { name: 'The ranking against 0050' })
    expect(screen.queryByText(/^Computing…/)).not.toBeInTheDocument()
  })

  it('tells a user that the administrator can backfill the history when there is nothing to rank yet, and names no command', async () => {
    const asked = serve({ latest: refusal('ranking_unavailable', 'No ranking can be made yet: the daily history holds no session.') })
    open()

    expect(await screen.findByText('Nothing to rank yet')).toBeVisible()
    expect(screen.getByText('The site administrator can bring the history back.')).toBeVisible()
    expect(screen.queryByText('just backfill-history')).not.toBeInTheDocument()
    expect(asked).toEqual(['latest'])
  })

  it('shows the backfill command to an administrator', async () => {
    serve({ latest: refusal('ranking_unavailable', 'No ranking can be made yet: the daily history holds no session.') })
    session.signIn({ ...TEST_ADMIN, permissions: [...TEST_ADMIN.permissions, 'see_administrator_features'] })
    open()

    expect(await screen.findByText('Nothing to rank yet')).toBeVisible()
    expect(screen.getByText('just backfill-history')).toBeVisible()
  })

  it('says so when the month read has no revenue to rank by', async () => {
    serve({ latest: () => json({ ...LATEST, scored: 0, stocks: [] }) })
    open()

    expect(await screen.findByText('Nothing could be ranked this month')).toBeVisible()
    expect(screen.getByText('The site administrator can bring the history back.')).toBeVisible()
    expect(screen.queryByTestId('turnover')).not.toBeInTheDocument()
  })

  it('explains a period without a decision and goes back to the whole history', async () => {
    const asked = serve({
      backtest: (first) => (first === '2026-11-14' ? refusal('backtest_period_unavailable', 'A ranking backtest needs a decision session from 2026-11-14 to 2026-11-30.')() : json(BACKTEST)),
    })
    open('/ranking?first=2026-11-14&last=2026-11-30')

    expect(await screen.findByText('This period holds no decision')).toBeVisible()
    expect(screen.getByLabelText('From')).toHaveValue('2026-11-14')
    expect(screen.getByRole('table', { name: "This month's ranking" })).toBeVisible()
    expect(screen.queryByRole('table', { name: 'Backtest: every past decision' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Show the whole history' }))
    expect(await screen.findByRole('table', { name: 'The ranking against 0050' })).toBeVisible()
    expect(asked).toContain('2000-01-01..2026-11-12')
  })

  it('shows a lost connection with a retry that asks again', async () => {
    let online = false
    const asked = serve({ latest: () => (online ? json(LATEST) : Promise.reject(new TypeError('Failed to fetch'))) })
    open()

    expect(await screen.findByText('The latest ranking could not be loaded.')).toBeVisible()
    online = true
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('table', { name: "This month's ranking" })).toBeVisible()
    expect(asked.filter((item) => item === 'latest')).toHaveLength(2)
  })

  it('asks a signed-out visitor to sign in and requests nothing', () => {
    session.signOut()
    const asked = serve()
    open()

    expect(screen.getByText('Sign in to see the monthly ranking')).toBeVisible()
    expect(asked).toEqual([])
  })

  it('reads in Traditional Chinese', async () => {
    serve()
    open('/ranking', 'zh-TW')

    expect(await screen.findByRole('table', { name: '排名組合與 0050 的比較' })).toHaveTextContent('平均每年+79.6%+37.5%')
    expect(screen.getByRole('heading', { name: /回測.*模擬/ })).toBeVisible()
    const rows = within(screen.getByRole('table', { name: '這個月的排名' })).getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('2.09 倍')
    expect(rows[0]).toHaveTextContent('創新高')
    expect(screen.getByRole('button', { name: '新進 2 · 移出 2' })).toBeVisible()
    expect(screen.getByText('下次決策約 11/13')).toBeVisible()
  })

  it('reads the mock account’s follow in Traditional Chinese', async () => {
    serve({ follow: [A_MONTH_IN] })
    open('/ranking', 'zh-TW', true)

    const block = await screen.findByRole('region', { name: '模擬帳戶跟單' })
    expect(await within(block).findByText('18／20')).toBeVisible()
    expect(block).toHaveTextContent('自 9/15')
    expect(within(block).getByText('要跟上：賣出 1 檔、買進 2 檔。')).toBeVisible()
    expect(within(block).getByRole('button', { name: '跟單這個月的排名' })).toBeEnabled()
  })
})
