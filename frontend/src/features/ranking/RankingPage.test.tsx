import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { TEST_ADMIN, TEST_USER } from '@/test/users'
import type { Ranking, RankingBacktest, RankingFollow } from './model'
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

interface Site {
  latest?: () => Response | Promise<Response>
  /** What a replay of a period other than the last two decisions answers. */
  backtest?: (first: string, last: string) => Response | Promise<Response>
  /** The mock account against the ranking; a second one is what the read after a follow started answers. */
  follow?: RankingFollow[]
}

const HOLDINGS = { decided_on: LATEST.decided_on, held: [], lacking: LATEST.stocks.map((stock) => stock.stock_id), left: [] }
const NEVER_FOLLOWED: RankingFollow = { holdings: HOLDINGS, refusal: null, running: false, performance: null }
/** A month after the first follow: 18 of the 20 held, the two that entered lacking and one that left still held. */
const A_MONTH_IN: RankingFollow = {
  holdings: { ...HOLDINGS, held: HOLDINGS.lacking.slice(2), lacking: HOLDINGS.lacking.slice(0, 2), left: ['1101'] },
  refusal: null,
  running: false,
  performance: { since: '2026-09-15', until: '2026-10-13', account_return: 0.0312, benchmark_id: '0050', benchmark_return: 0.021 },
}

/** The ranking endpoints as the backend answers them; returns the replays asked, each as `first..last`. */
function serve({ latest = () => json(LATEST), backtest = () => json(BACKTEST), follow = [NEVER_FOLLOWED] }: Site = {}) {
  const asked: string[] = []
  const answers = [...follow]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const { pathname, searchParams } = new URL(url, 'http://localhost')
      if (pathname === '/v1/market/audience') return json(PERSONAL_SITE)
      if (pathname === '/v1/rankings/follow') {
        asked.push(`${init?.method ?? 'GET'} follow`)
        return init?.method === 'POST' ? json({ run_id: '00000000-0000-0000-0000-000000000001' }, 202) : json(answers.length > 1 ? answers.shift() : answers[0])
      }
      if (pathname === '/v1/rankings/latest') {
        asked.push('latest')
        return latest()
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

function open(address = '/ranking', locale: 'en' | 'zh-TW' = 'en', mockAccount = false) {
  const i18n = initI18n('en')
  void i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={[address]}>
          <RankingPage mockAccount={mockAccount} />
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

    expect(screen.getByText('10/13/2026')).toBeVisible()
    expect(screen.getByText('September 2026')).toBeVisible()
    expect(screen.getByText('About 11/13')).toBeVisible()
    expect(screen.getByText('757 stocks')).toBeVisible()
    expect(screen.getByText('759 passed the traded-value and price floor')).toBeVisible()
  })

  it('asks nothing about the mock account where the site does not show it', async () => {
    const asked = serve()
    open()

    await screen.findByTestId('headline')
    expect(screen.queryByRole('region', { name: 'The ranking in your mock account' })).not.toBeInTheDocument()
    expect(asked.filter((request) => request.endsWith('follow'))).toEqual([])
  })

  it('says in one sentence that the mock account does not follow yet, and follows the ranking after a yes that lists every order', async () => {
    const asked = serve({ follow: [NEVER_FOLLOWED, { ...NEVER_FOLLOWED, running: true }] })
    const user = userEvent.setup()
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByText('Your mock account does not follow the ranking yet.')).toBeVisible()
    expect(within(block).getByRole('link', { name: 'Mock account' })).toHaveAttribute('href', '/account')
    expect(within(block).queryByText('Holds')).not.toBeInTheDocument()

    await user.click(within(block).getByRole('button', { name: 'Follow this month’s ranking' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Bring your mock account to this month’s ranking?' })
    const listed = within(dialog).getAllByRole('listitem').map((item) => item.textContent)
    expect(listed).toHaveLength(20)
    expect(listed.slice(0, 2)).toEqual([`${LATEST.stocks[0]!.stock_id} AlphaBUY`, `${LATEST.stocks[1]!.stock_id} BetaBUY`])
    expect(within(dialog).getByText(/at a realtime quote now\. Only your mock account changes; no real money moves\./)).toBeVisible()
    expect(asked).not.toContain('POST follow')

    await user.click(within(dialog).getByRole('button', { name: 'Follow' }))
    expect(await within(block).findByText('A run is in progress…')).toBeVisible()
    expect(within(block).getByRole('button', { name: 'Follow this month’s ranking' })).toBeDisabled()
    expect(asked.filter((request) => request === 'POST follow')).toHaveLength(1)
  })

  it('says what the mock account holds of the ranking and what it made since its first follow against the benchmark', async () => {
    serve({ follow: [A_MONTH_IN] })
    const user = userEvent.setup()
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByText('18 of 20')).toBeVisible()
    expect(block).toHaveTextContent('Mock accountUp +3.12%0050, same sessionsUp +2.10%')
    expect(within(block).getByText('Since the first follow on 09/15/2026, to the close of 10/13/2026, after fees and tax.')).toBeVisible()
    expect(block).toHaveTextContent(`Not held yet: ${A_MONTH_IN.holdings.lacking.join(' ')}`)
    expect(block).toHaveTextContent('Left the ranking, still held: 1101')
    expect(within(block).getByText('To match this month’s ranking: 1 to sell, 2 to buy.')).toBeVisible()

    await user.click(within(block).getByRole('button', { name: 'Follow this month’s ranking' }))
    const listed = within(await screen.findByRole('alertdialog')).getAllByRole('listitem').map((item) => item.textContent)
    expect(listed).toEqual(['1101 SELL', `${LATEST.stocks[0]!.stock_id} AlphaBUY`, `${LATEST.stocks[1]!.stock_id} BetaBUY`])
  })

  it('offers no follow once the mock account holds the ranking, and says why one cannot start outside the window', async () => {
    const held = { ...A_MONTH_IN.holdings, held: HOLDINGS.lacking, lacking: [], left: [] }
    serve({ follow: [{ ...A_MONTH_IN, holdings: held, refusal: 'nothing_to_follow' }] })
    open('/ranking', 'en', true)

    const block = await screen.findByRole('region', { name: 'The ranking in your mock account' })
    expect(await within(block).findByText('Your mock account holds this month’s ranking.')).toBeVisible()
    expect(within(block).getByText('20 of 20')).toBeVisible()
    expect(within(block).queryByRole('button', { name: 'Follow this month’s ranking' })).not.toBeInTheDocument()
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

    expect(await screen.findByText('Should be here by now')).toBeVisible()
    expect(screen.getByText(/^Expected around 11\/13\./)).toBeVisible()
  })

  it('marks the stocks that entered since the decision before and lists the ones that left', async () => {
    serve()
    open()

    const changed = await screen.findByText('Against the decision before (9/14): 2 entered, 2 left, 18 stayed.')
    expect(changed).toBeVisible()
    const left = screen.getByRole('list', { name: 'Left' })
    expect(within(left).getByRole('link', { name: /Gamma/ })).toHaveAttribute('href', '/stocks/1101')
    expect(within(left).getByRole('link', { name: '1102' })).toHaveAttribute('href', '/stocks/1102')
    const rows = within(screen.getByRole('table', { name: "This month's ranking" })).getAllByRole('row').slice(1)
    expect(rows.filter((row) => within(row).queryByText('New'))).toHaveLength(2)
    expect(within(rows[0]!).getByText('New')).toBeVisible()
  })

  it('answers whether following it beat the benchmark: a sentence, both sides of each figure, every year and the costs', async () => {
    const asked = serve()
    open()

    expect(await screen.findByTestId('headline')).toHaveTextContent(
      '01/13/2023 to 10/30/2024: trading to the ranking every month returned +79.6% a year on average. Holding 0050 over the same time returned +37.5% a year.',
    )
    expect(screen.getByRole('heading', { name: 'Backtest (simulated): would following it have beaten 0050?' })).toBeVisible()
    const compared = screen.getByRole('table', { name: 'The ranking against 0050' })
    expect(within(compared).getByRole('row', { name: /A year on average/ })).toHaveTextContent('+79.6%+37.5%')
    expect(within(compared).getByRole('row', { name: /1 put in at the start became/ })).toHaveTextContent('2.81.7')
    expect(within(compared).getByRole('row', { name: /Deepest fall/ })).toHaveTextContent(/[-−]16\.6%[-−]21\.3%/)
    expect(screen.getByText(/add up to about 9\.6% of the value they were paid from \(0\.1425% fee, 0\.3% tax on a sale\)/)).toBeVisible()

    const years = screen.getByRole('table', { name: 'Every year' })
    expect(within(years).getByRole('row', { name: /2024/ })).toHaveTextContent('to 10/30')
    expect(within(years).getByRole('row', { name: /2024/ })).toHaveTextContent('Up +81.0%Up +45.6%+35.3 points')
    expect(within(years).getByRole('row', { name: /2023/ })).toHaveTextContent('from 1/13')

    expect(asked[0]).toBe('latest')
    expect(asked.slice(1).sort()).toEqual(['2000-01-01..2026-11-12', '2026-09-01..2026-10-13'])
  })

  it('marks a year the ranking lost money in and one it fell behind the benchmark in', async () => {
    serve({
      backtest: () =>
        json({ ...BACKTEST, yearly_returns: { 2023: -0.25, 2024: 0.1 }, benchmark_yearly_returns: { 2023: -0.21, 2024: 0.2 }, annual_return: 0.1, benchmark_annual_return: 0.2 }),
    })
    open()

    const years = await screen.findByRole('table', { name: 'Every year' })
    expect(within(years).getByRole('row', { name: /2023/ })).toHaveTextContent('Lost money')
    expect(within(years).getByRole('row', { name: /2023/ })).toHaveTextContent('Behind 0050')
    expect(within(years).getByRole('row', { name: /2024/ })).not.toHaveTextContent('Lost money')
    expect(within(years).getByRole('row', { name: /2024/ })).toHaveTextContent('Behind 0050')
    expect(screen.getByText('2 years · 1 lost money · 2 behind the benchmark')).toBeVisible()
    expect(screen.getByTestId('headline')).toHaveTextContent('returned +10.0% a year on average, less than the +20.0% a year of holding 0050.')
  })

  it('says each measured caveat beside the record', async () => {
    serve()
    open()

    expect(await screen.findByText('This is a backtest, not a track record.')).toBeVisible()
    expect(screen.getByText(/In 2018, 40 of the 521 liquid stocks had no revenue data, and 37 of them later delisted\./)).toBeVisible()
    expect(screen.getByText('The formula was the best of about 60 tried.')).toBeVisible()
    expect(screen.getByText(/It fell about 25% in 2022, and its deepest fall from a high was about 36%\./)).toBeVisible()
    expect(screen.getByText('Buying a few days late cut the result sharply.')).toBeVisible()
    expect(within(document.getElementById('ranking-caveats')!).getByText('For research and reference only, not investment advice.')).toBeVisible()
  })

  it('asks for a quick period once, and for two typed days only when they are applied', async () => {
    const asked = serve()
    open()
    await screen.findByTestId('headline')
    const replays = () => asked.filter((item) => item !== 'latest' && !item.startsWith('2026-09-01'))
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
    expect(screen.getByText(/The first answer after it starts takes about a minute/)).toBeVisible()
    expect(asked).toEqual(['latest'])

    answer(json(LATEST))
    expect(await screen.findByRole('table', { name: "This month's ranking" })).toBeVisible()
    await screen.findByTestId('headline')
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
    expect(await screen.findByTestId('headline')).toBeVisible()
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

    expect(screen.getByText('Sign in to see the monthly revenue ranking')).toBeVisible()
    expect(asked).toEqual([])
  })

  it('reads in Traditional Chinese', async () => {
    serve()
    open('/ranking', 'zh-TW')

    expect(await screen.findByTestId('headline')).toHaveTextContent('2023/01/13 到 2024/10/30，每個月照排名換股，平均每年 +79.6%；同一段時間一直抱著 0050，平均每年 +37.5%。')
    const rows = within(screen.getByRole('table', { name: '這個月的排名' })).getAllByRole('row').slice(1)
    expect(rows[0]).toHaveTextContent('2.09 倍')
    expect(rows[0]).toHaveTextContent('創一年新高')
    expect(screen.getByText('和上次決策（9/14）相比：新進 2 檔、移出 2 檔、續抱 18 檔。')).toBeVisible()
    expect(screen.getByText('約 11/13')).toBeVisible()
  })

  it('reads the mock account’s follow in Traditional Chinese', async () => {
    serve({ follow: [A_MONTH_IN] })
    open('/ranking', 'zh-TW', true)

    const block = await screen.findByRole('region', { name: '模擬帳戶跟單' })
    expect(await within(block).findByText('18／20 檔')).toBeVisible()
    expect(within(block).getByText('自 2026/09/15 第一次跟單，到 2026/10/13 收盤，已扣手續費與稅。')).toBeVisible()
    expect(within(block).getByText('要跟上這個月的排名：賣出 1 檔、買進 2 檔。')).toBeVisible()
    expect(within(block).getByRole('button', { name: '跟單這個月的排名' })).toBeEnabled()
  })
})
