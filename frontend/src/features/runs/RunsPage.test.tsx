import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { Toaster } from 'sonner'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { RunsPage } from './RunsPage'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** Starts a Full Cycle against a server that refuses it with this answer. */
async function startRefused(status: number, refusal: { detail: string; code: string }) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/v1/market/audience') return json(PERSONAL_SITE)
      if (url.startsWith('/v1/runs?')) return json([])
      if (url === '/v1/runs/full-cycle' && init?.method === 'POST') return json(refusal, status)
      return json({ detail: 'Not Found', code: 'not_found' }, 404)
    }),
  )
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <RunsPage />
          <Toaster />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
  const user = userEvent.setup()
  const [fullCycle] = await screen.findAllByRole('button', { name: 'Start' })
  await user.click(fullCycle!)
  await user.click(await screen.findByRole('button', { name: 'Start the run' }))
}

describe('a run the server refuses to start', { timeout: 20_000 }, () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('says another run is still going when the server says so', async () => {
    await startRefused(409, { detail: 'Your run is still running.', code: 'run_in_progress' })

    expect(await screen.findByText('Another run is still going. Wait for it to end.')).toBeInTheDocument()
  })

  it('names the mock broker only for its own refusal, not for every 403', async () => {
    const detail = 'This installation trades on a real broker. Only an administrator may use its private pages.'
    await startRefused(403, { detail, code: 'real_broker_refused' })

    expect(await screen.findByText(`The run did not start: ${detail}`)).toBeInTheDocument()
    expect(screen.queryByText('This workflow runs from the web only on the mock broker.')).not.toBeInTheDocument()
  })
})

const ENDED = '22222222-2222-4222-8222-222222222222'
const RUNNING = '33333333-3333-4333-8333-333333333333'

const run = (runId: string, state: 'running' | 'finished') => ({
  run_id: runId,
  state,
  error: null,
  reports: [],
  summary: { workflow: 'full_cycle', start_time: '2026-11-05T01:00:00Z', end_time: state === 'running' ? null : '2026-11-05T01:12:00Z', signals_generated: 7, orders_submitted: 0, errors: [] },
})
const signal = (stockId: string, action: 'buy' | 'sell' | 'hold', score: number) => ({
  decision_id: `decision-${stockId}`,
  stock_id: stockId,
  action,
  score,
  quantity: 1000,
  price_at_signal: 100,
  reason: `${action} ${stockId}`,
})

/** The runs page against a server that lists these runs, newest first, and these decisions per run. */
function renderRuns(runs: unknown[], decisions: Record<string, unknown[]> = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/v1/market/audience') return json(PERSONAL_SITE)
      if (url.startsWith('/v1/runs?')) return json(runs)
      const runId = url.match(/^\/v1\/runs\/([^/]+)\/signals$/)?.[1]
      if (runId && decisions[runId]) return json(decisions[runId])
      return json({ detail: 'Not Found', code: 'not_found' }, 404)
    }),
  )
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <RunsPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the latest result', { timeout: 20_000 }, () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('lists the newest ended run’s five strongest decisions, BUY first and then by score, each opening its stock', async () => {
    renderRuns([run(RUNNING, 'running'), run(ENDED, 'finished')], {
      [ENDED]: [
        signal('2317', 'sell', 95),
        signal('2454', 'hold', 90),
        signal('2330', 'buy', 70),
        signal('2603', 'buy', 88),
        signal('3008', 'buy', 60),
        signal('1101', 'sell', 50),
        signal('2412', 'hold', 85),
      ],
    })

    const latest = await screen.findByRole('region', { name: 'Latest result' })
    const table = await within(latest).findByRole('table', { name: 'Latest result' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => within(row).getAllByRole('cell').slice(0, 3).map((cell) => cell.textContent))).toEqual([
      ['2603', 'BUY', '88'],
      ['2330', 'BUY', '70'],
      ['3008', 'BUY', '60'],
      ['2317', 'SELL', '95'],
      ['2454', 'HOLD', '90'],
    ])
    expect(within(table).getByRole('link', { name: '2603' })).toHaveAttribute('href', '/stocks/2603')
    expect(within(latest).getByText(/^Full Cycle · Started/)).toBeInTheDocument()
    expect(within(latest).getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', `/runs/${ENDED}`)
  })

  it('adds nothing while no run has ended', async () => {
    renderRuns([run(RUNNING, 'running')])

    await screen.findByRole('table', { name: 'Recorded runs' })
    expect(screen.queryByRole('region', { name: 'Latest result' })).not.toBeInTheDocument()
  })
})
