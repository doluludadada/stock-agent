import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type Schemas } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { OPEN_SITE } from '@/test/features'
import { TEST_USER } from '@/test/users'
import { runKeys } from './api'
import { RunDetailPage } from './RunDetailPage'

const RUN = '11111111-1111-4111-8111-111111111111'
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function renderRun() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <RunDetailPage runId={RUN} />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('a finished run whose decisions or orders failed to load', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('says the load failed and retries it, instead of saying the run made no decision and placed no order', async () => {
    let failing = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/v1/auth/status') return json(OPEN_SITE)
      if (url === `/v1/runs/${RUN}`) return json({ run_id: RUN, state: 'finished', error: null, summary: null, reports: [] })
      return failing ? json({ detail: 'boom' }, 500) : json([])
    }))
    renderRun()

    const failures = await screen.findAllByRole('button', { name: 'Try again' })
    expect(failures).toHaveLength(2)
    expect(screen.queryByText('The run recorded no decision.')).not.toBeInTheDocument()
    expect(screen.queryByText('The run placed no order.')).not.toBeInTheDocument()

    failing = false
    const user = userEvent.setup()
    for (const retry of failures) await user.click(retry)

    expect(await screen.findByText('The run recorded no decision.')).toBeInTheDocument()
    expect(await screen.findByText('The run placed no order.')).toBeInTheDocument()
    expect(within(document.body).queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })
})

describe('a running run whose poll fails', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('stays on screen, and shows the run’s end when a later poll answers', async () => {
    const server: { answer: 'running' | 'down' | 'finished' } = { answer: 'running' }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/v1/auth/status') return json(OPEN_SITE)
      if (url !== `/v1/runs/${RUN}`) return json([])
      if (server.answer === 'down') return json({ detail: 'boom' }, 500)
      return json({ run_id: RUN, state: server.answer, error: null, summary: null, reports: [] })
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <RunDetailPage runId={RUN} />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>,
    )
    expect(await screen.findByText('Running. The state updates by itself.')).toBeVisible()

    server.answer = 'down'
    await act(async () => {
      await client.refetchQueries({ queryKey: runKeys.run(RUN) })
      // The page hears of the failed poll a moment after the poll settles.
      await new Promise((resolve) => setTimeout(resolve, 20))
    })
    expect(client.getQueryState(runKeys.run(RUN))?.status).toBe('error')
    expect(screen.getByText('Running. The state updates by itself.')).toBeVisible()
    expect(screen.getByText(RUN)).toBeVisible()
    expect(screen.queryByText('The runs could not be loaded.')).not.toBeInTheDocument()

    server.answer = 'finished'
    await act(() => client.refetchQueries({ queryKey: runKeys.run(RUN) }))
    expect(await screen.findByText('The run recorded no decision.')).toBeVisible()
    expect(screen.queryByText('Running. The state updates by itself.')).not.toBeInTheDocument()
  })
})

const FOLLOW_RUN = '22222222-2222-4222-8222-222222222222'
const BUY ='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const SELL = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const HOLD = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'

type Follow = Schemas['FollowResponse']

const summary = (workflow: Schemas['Workflow'], followed_run_id: string | null = null): Schemas['RunSummary'] => ({
  workflow,
  execution_provider: 'mock',
  start_time: '2026-11-05T13:00:00Z',
  end_time: '2026-11-05T13:20:00Z',
  total_scanned: 1900,
  buzz_scanned: 0,
  buzz_qualified: 0,
  passed_technical: 3,
  ai_analysed: 3,
  signals_generated: 3,
  orders_submitted: 0,
  orders_refused: 0,
  stale_market_data_count: 0,
  errors: [],
  execution_log: [],
  followed_run_id,
  technical_strategy_id: null,
})

const decision = (decision_id: string, stock_id: string, action: Schemas['TradeAction'], quantity: number): Schemas['SignalResponse'] => ({
  decision_id,
  stock_id,
  action,
  source: 'combined',
  score: 80,
  reason: 'Strong trend',
  quantity,
  stop_loss_price: null,
  generated_at: '2026-11-05T13:10:00Z',
  price_at_signal: 500,
  price_observed_at: '2026-11-05T05:30:00Z',
  history_until: null,
  technical_report: null,
  ai_report: null,
})

const DECISIONS = [decision(BUY, '2330', 'buy', 1000), decision(SELL, '2317', 'sell', 500), decision(HOLD, '2454', 'hold', 0)]

const order = (status: Schemas['OrderStatus'], filled: number, reason: string | null = null): Schemas['Order'] => ({
  id: `order-${status}`,
  run_id: FOLLOW_RUN,
  decision_id: `follow-${status}`,
  stock_id: '2330',
  action: 'buy',
  order_type: 'limit',
  quantity: 1000,
  limit_price: 512,
  price_at_signal: 512,
  time_in_force: 'ioc',
  status,
  reason,
  filled_quantity: filled,
  average_filled_price: filled > 0 ? 512 : null,
  fee: 729,
  tax: 0,
  realized_pnl: null,
  created_at: '2026-11-06T02:05:00Z',
  updated_at: '2026-11-06T02:05:00Z',
})

const followed = (status: Schemas['OrderStatus'], filled: number, reason: string | null = null): Schemas['FollowItem'] => ({
  decision: { ...decision(`follow-${status}`, '2330', 'buy', 1000), source: 'follow', followed_decision_id: BUY },
  order: order(status, filled, reason),
})

interface Site {
  follow: Follow | { status: number; body: { detail: string; code: string } }
  audience?: Schemas['AudienceResponse']
}

/** A finished Full Cycle with a BUY, a SELL and a HOLD, the follow the server answers for it, and the follow's own run. */
function serve({ follow, audience = PERSONAL_SITE }: Site) {
  const posts: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/v1/auth/status') return json(OPEN_SITE)
      if (url === '/v1/market/audience') return json(audience)
      if (url === `/v1/runs/${RUN}`) {
        const reports = [{ stock_id: '2330', name: 'TSMC', technical_report: null, ai_report: null, composite_score: 80, current_price: 500, latest_market_data_at: null }]
        return json({ run_id: RUN, state: 'finished', error: null, summary: summary('full_cycle'), reports })
      }
      if (url === `/v1/runs/${RUN}/signals`) return json(DECISIONS)
      if (url === `/v1/runs/${RUN}/follow` && init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) })
        return json({ run_id: FOLLOW_RUN }, 202)
      }
      if (url === `/v1/runs/${RUN}/follow`) return 'status' in follow ? json(follow.body, follow.status) : json(follow)
      if (url === `/v1/runs/${FOLLOW_RUN}`) return json({ run_id: FOLLOW_RUN, state: 'running', error: null, summary: summary('follow', RUN), reports: [] })
      if (url.endsWith('/orders') || url.endsWith('/signals')) return json([])
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  return posts
}

function RunAt() {
  const { runId = '' } = useParams()
  return <RunDetailPage key={runId} runId={runId} />
}

function openRun() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={[`/runs/${RUN}`]}>
          <Routes>
            <Route path="/runs/:runId" element={<RunAt />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

const decisionRow = (stock: string) => within(screen.getByRole('table', { name: 'Decisions (3)' })).getByRole('row', { name: new RegExp(stock) })

describe('following a finished Full Cycle into the mock account', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('says what a follow places and at which price, lists each open decision before it starts, and opens the follow’s run', async () => {
    const posts = serve({ follow: { refusal: null, open_decision_ids: [BUY, SELL], follows: [] } })
    const user = userEvent.setup()
    openRun()

    expect(await screen.findByText('Places the decisions of this run still open (2) in your mock account at a realtime quote now.')).toBeVisible()
    expect(within(decisionRow('2330')).getByText('Open')).toBeVisible()
    expect(within(decisionRow('2454')).queryByText('Open')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Follow in my mock account' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Follow this run in your mock account?' })
    const listed = within(dialog).getAllByRole('listitem').map((item) => item.textContent)
    expect(listed).toEqual(['2330 TSMCBUY · 1,000 shares', '2317 SELL · 500 shares'])
    expect(within(dialog).getByText('A SELL sells only the shares you hold then.')).toBeVisible()
    expect(posts).toEqual([])

    await user.click(within(dialog).getByRole('button', { name: 'Follow' }))
    expect(await screen.findByRole('link', { name: 'Open that run' })).toHaveAttribute('href', `/runs/${RUN}`)
    expect(screen.getByRole('heading', { name: 'Follow', level: 1 })).toBeVisible()
    expect(posts).toEqual([{ url: `/v1/runs/${RUN}/follow`, body: { confirm: true } }])
  })

  it('names the official close where the site fills a follow there', async () => {
    serve({ follow: { refusal: null, open_decision_ids: [BUY], follows: [] }, audience: { ...PERSONAL_SITE, order_pricing: 'official_close' } })
    openRun()

    expect(await screen.findByText('Places the decisions of this run still open (1) in your mock account at the official close of the last session.')).toBeVisible()
  })

  it('outside the follow window, says when the window is and keeps the button disabled', async () => {
    serve({ follow: { refusal: 'outside_follow_window', open_decision_ids: [BUY, SELL], follows: [] } })
    openRun()

    const reason = await screen.findByText(/^Not now\. This site follows at a realtime quote, so only in continuous trading: Monday to Friday, 09:00 to 13:25 Taipei time\.$/)
    const button = screen.getByRole('button', { name: 'Follow in my mock account' })
    expect(button).toBeDisabled()
    expect(button).toHaveAccessibleDescription(reason.textContent ?? '')
  })

  it('on a site that follows at a realtime quote but has none now, says why and offers no follow', async () => {
    const posts = serve({ follow: { refusal: null, open_decision_ids: [BUY, SELL], follows: [] }, audience: { ...PERSONAL_SITE, realtime_quotes: false } })
    openRun()

    const reason = await screen.findByText(/^Not now\. This site follows at a realtime quote, and it has no Shioaji login now/)
    const button = screen.getByRole('button', { name: 'Follow in my mock account' })
    expect(button).toBeDisabled()
    expect(button).toHaveAccessibleDescription(reason.textContent ?? '')
    expect(posts).toEqual([])
  })

  it('once every decision is followed, says so, marks them, and lists each follow with its outcome and its run', async () => {
    const filled = followed('filled', 1000)
    const refused = followed('rejected', 0, 'SESSION_IN_PROGRESS: the session trades now')
    serve({ follow: { refusal: 'nothing_to_follow', open_decision_ids: [], follows: [refused, filled] } })
    openRun()

    expect(await screen.findByText(/^Every BUY and SELL of this run is in your mock account already\./)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Follow in my mock account' })).toBeDisabled()
    expect(within(decisionRow('2330')).getByText('Followed')).toBeVisible()

    const follows = within(screen.getByRole('table', { name: 'Follows of this run' }))
    expect(follows.getByText('Filled 1,000 @ 512.00')).toBeVisible()
    expect(follows.getByText('Rejected: SESSION_IN_PROGRESS: the session trades now')).toBeVisible()
    for (const link of follows.getAllByRole('link', { name: /^Open the follow of / })) expect(link).toHaveAttribute('href', `/runs/${FOLLOW_RUN}`)
  })

  it('says a run with no BUY or SELL has nothing to follow', async () => {
    serve({ follow: { refusal: 'nothing_to_follow', open_decision_ids: [], follows: [] } })
    openRun()

    expect(await screen.findByText('This run made no BUY or SELL, so there is nothing to follow.')).toBeVisible()
  })

  it('offers no manual BUY on a Full Cycle', async () => {
    serve({ follow: { refusal: null, open_decision_ids: [BUY], follows: [] } })
    openRun()

    expect(await screen.findByRole('heading', { name: 'Stock reports' })).toBeVisible()
    expect(screen.queryByRole('button', { name: /^Buy / })).not.toBeInTheDocument()
  })
})

const BUY_RUN = '44444444-4444-4444-8444-444444444444'
const MOCK = { broker: 'mock', server: null, max_order_equity_pct: null, max_daily_buy_equity_pct: null }
const SINOPAC = { broker: 'shioaji', server: 'simulation', max_order_equity_pct: 0.25, max_daily_buy_equity_pct: 1.1 }

/** A finished specific-stock analysis that reported 2330 and 2317, the brokers offered, and the BUY's own run. */
function serveSpecific({ audience = PERSONAL_SITE, brokers = [MOCK, SINOPAC] }: { audience?: Schemas['AudienceResponse']; brokers?: unknown[] } = {}) {
  const buys: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/v1/auth/status') return json(OPEN_SITE)
      if (url === '/v1/market/audience') return json(audience)
      if (url === '/v1/account/brokers') return json(brokers)
      if (url === `/v1/runs/${RUN}`) {
        const report = (stock_id: string, name: string) => ({ stock_id, name, technical_report: null, ai_report: null, composite_score: 70, current_price: 500, latest_market_data_at: null })
        return json({ run_id: RUN, state: 'finished', error: null, summary: summary('specific_stocks'), reports: [report('2330', 'TSMC'), report('2317', 'Hon Hai')] })
      }
      if (url.startsWith(`/v1/runs/${RUN}/manual-buy`) && init?.method === 'POST') {
        buys.push({ url, body: JSON.parse(String(init.body)) })
        return json({ run_id: BUY_RUN }, 202)
      }
      if (url === `/v1/runs/${BUY_RUN}`) return json({ run_id: BUY_RUN, state: 'running', error: null, summary: { ...summary('manual_buy'), execution_provider: 'shioaji' }, reports: [] })
      if (url.endsWith('/orders') || url.endsWith('/signals')) return json([])
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  return buys
}

describe('a manual BUY of a stock a specific-stock analysis reported', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('asks for whole shares, names the stock, the shares and the account, and opens the BUY’s run on the account chosen', async () => {
    const buys = serveSpecific()
    const user = userEvent.setup()
    openRun()

    expect(await screen.findByRole('button', { name: 'Buy 2317 Hon Hai' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Buy 2330 TSMC' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Buy 2330 TSMC?' })
    const go = within(dialog).getByRole('button', { name: 'Buy' })
    expect(go).toBeDisabled()

    const shares = within(dialog).getByRole('spinbutton', { name: 'Shares' })
    await user.type(shares, '1.5')
    expect(within(dialog).getByText('Enter a whole number of shares above 0.')).toBeVisible()
    expect(go).toBeDisabled()

    await user.clear(shares)
    await user.type(shares, '1000')
    expect(within(dialog).getByText('BUY 1,000 shares of 2330 TSMC · Mock account')).toBeVisible()
    await user.click(await within(dialog).findByRole('radio', { name: 'SinoPac account · Simulation' }))
    expect(within(dialog).getByText('SinoPac account: Simulation, no real money')).toBeVisible()
    expect(within(dialog).getByText(/^Each BUY up to 25% of the account’s equity, and BUYs up to 110% of it per Taiwan day\./)).toBeVisible()
    expect(within(dialog).getByText('BUY 1,000 shares of 2330 TSMC · SinoPac account')).toBeVisible()
    expect(buys).toEqual([])

    await user.click(go)
    expect(await screen.findByRole('heading', { name: 'Manual BUY', level: 1 })).toBeVisible()
    expect(screen.getByText('SinoPac account')).toBeVisible()
    expect(buys).toEqual([{ url: `/v1/runs/${RUN}/manual-buy?broker=shioaji&server=simulation`, body: { confirm: true, stock_id: '2330', quantity: 1000 } }])
  })

  it('offers no BUY where the site has no realtime quote to price it', async () => {
    serveSpecific({ audience: { ...PERSONAL_SITE, realtime_quotes: false } })
    openRun()

    expect(await screen.findByRole('heading', { name: 'Stock reports' })).toBeVisible()
    expect(screen.queryByRole('button', { name: /^Buy / })).not.toBeInTheDocument()
  })
})
