import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type Schemas } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { RunDetailPage } from './RunDetailPage'

const RUN = '11111111-1111-4111-8111-111111111111'
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function renderRun() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <RunDetailPage runId={RUN} ruleName={(name) => name} />
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

const FOLLOW_RUN = '22222222-2222-4222-8222-222222222222'
const BUY = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const SELL = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const HOLD = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'

type Follow = Schemas['FollowResponse']

const summary = (workflow: Schemas['Workflow'], followed_run_id: string | null = null): Schemas['RunSummary'] => ({
  workflow,
  execution_provider: 'mock',
  order_mode: 'mock_only',
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
  return <RunDetailPage key={runId} runId={runId} ruleName={(name) => name} />
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

  it('shows no follow on an installation whose broker is not the mock', async () => {
    serve({ follow: { status: 403, body: { detail: 'Only on the mock broker.', code: 'mock_broker_only' } } })
    openRun()

    expect(await screen.findByRole('table', { name: 'Decisions (3)' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Follow in your mock account' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Follow' })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
