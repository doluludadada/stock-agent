import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { useAccountHistory } from '@/features/account/api'
import { runKeys, useRun } from '@/features/runs/api'
import { useWatchlistEntries } from '@/features/watchlist/api'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'

const RUN = '11111111-1111-4111-8111-111111111111'

/** A run that is running until `finish`, which also fills an order and watches a stock. */
function fakeBackend() {
  const server = { running: true }
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  const fetch = vi.fn(async (input: string) => {
    const url = String(input)
    if (url === `/v1/runs/${RUN}`) return json({ run_id: RUN, state: server.running ? 'running' : 'finished', error: null, summary: null, reports: [] })
    if (url.startsWith('/v1/account/history')) {
      const value = { cash: server.running ? 1000 : 400, market_value: 0, unrealized_pnl: 0, equity: 1000, positions: [] }
      return json({ current: value, live_stock_ids: [], equity_curve: {}, as_of: null, execution_provider: 'mock', order_mode: 'mock_only' })
    }
    if (url === '/v1/watchlist') return json(server.running ? [] : [{ stock_id: '2330', name: 'TSMC', watchlist_type: 'technical', created_at: '2026-11-04T00:00:00Z', expires_at: null }])
    return json({ detail: `unexpected ${url}` })
  })
  return { server, fetch }
}

function Holdings() {
  const account = useAccountHistory(null)
  const watchlist = useWatchlistEntries()
  return <p>{account.data && watchlist.data ? `cash ${account.data.current.cash}, watching ${watchlist.data.length}` : 'loading'}</p>
}

function RunState() {
  const run = useRun(RUN)
  return <p>{run.data?.state ?? 'loading'}</p>
}

describe('a run that ends', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('makes the account and the watchlist load again, so they never show what was there before the run', async () => {
    const backend = fakeBackend()
    vi.stubGlobal('fetch', backend.fetch)
    session.signIn(TEST_USER)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>

    const before = render(<Holdings />, { wrapper })
    expect(await screen.findByText('cash 1000, watching 0')).toBeInTheDocument()
    before.unmount()

    render(<RunState />, { wrapper })
    expect(await screen.findByText('running')).toBeInTheDocument()
    backend.server.running = false
    await act(() => client.refetchQueries({ queryKey: runKeys.run(RUN) }))
    expect(await screen.findByText('finished')).toBeInTheDocument()

    render(<Holdings />, { wrapper })
    expect(await screen.findByText('cash 400, watching 1')).toBeInTheDocument()
  })
})
