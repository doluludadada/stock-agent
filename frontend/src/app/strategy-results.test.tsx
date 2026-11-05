import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { useStockTechnical } from '@/features/stock-research/api'
import { settingsFromApi } from '@/features/strategies/api/mapping'
import { useSaveStrategySettings } from '@/features/strategies/api/queries'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { useValuationScan } from '@/features/valuation/api'
import { session } from '@/shared/api'

/** The backend: it evaluates with whichever strategy is active, and a save switches it. */
function fakeBackend() {
  let active = 'balanced'
  let revision = 0
  const settings = () => ({ active_strategy_id: active, buzz_strategy_id: 'balanced', strategies: [builtInJson('balanced'), builtInJson('aggressive')], revision })
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    if (url.startsWith('/v1/market/stocks/2330/technical')) return json({ strategy: { name: active } })
    if (url.startsWith('/v1/valuation/scan')) return json({ technical_strategy_id: active })
    if (url === '/v1/technical-settings' && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body)) as { settings: { active_strategy_id: string; revision: number } }
      if (body.settings.revision !== revision) return json({ detail: 'stale' }, 409)
      active = body.settings.active_strategy_id
      revision += 1
      return json(settings())
    }
    return json({ detail: `unexpected ${url}` }, 404)
  })
  return { fetch, settings }
}

function StockEvaluation() {
  const technical = useStockTechnical('2330')
  return <p>{technical.data ? `evaluated with ${technical.data.strategy.name}` : 'evaluating'}</p>
}

function TechnicalScan() {
  const scan = useValuationScan({ targetPe: 15, minUndervaluation: 0.3, technical: true })
  return <p>{scan.data ? `scanned with ${scan.data.technical_strategy_id}` : 'scanning'}</p>
}

describe('saving or switching a strategy', () => {
  let client: QueryClient
  let backend: ReturnType<typeof fakeBackend>
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>

  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } })
    backend = fakeBackend()
    vi.stubGlobal('fetch', backend.fetch)
    session.unlock('owner', 'owner-token')
  })

  afterEach(() => {
    session.lock('owner')
    vi.unstubAllGlobals()
  })

  async function switchToAggressive() {
    const save = renderHook(() => useSaveStrategySettings(), { wrapper })
    const next = settingsFromApi({ ...backend.settings(), active_strategy_id: 'aggressive' })
    await act(() => save.result.current.mutateAsync(next))
  }

  it("never shows the stock's evaluation by the strategy that was replaced", async () => {
    const page = render(<StockEvaluation />, { wrapper })
    expect(await screen.findByText('evaluated with balanced')).toBeInTheDocument()
    page.unmount()

    await switchToAggressive()

    render(<StockEvaluation />, { wrapper })
    expect(screen.queryByText('evaluated with balanced')).not.toBeInTheDocument()
    expect(await screen.findByText('evaluated with aggressive')).toBeInTheDocument()
  })

  it('never shows a technical valuation scan by the strategy that was replaced', async () => {
    const page = render(<TechnicalScan />, { wrapper })
    expect(await screen.findByText('scanned with balanced')).toBeInTheDocument()
    page.unmount()

    await switchToAggressive()

    render(<TechnicalScan />, { wrapper })
    expect(screen.queryByText('scanned with balanced')).not.toBeInTheDocument()
    expect(await screen.findByText('scanned with aggressive')).toBeInTheDocument()
  })

  it('refreshes an evaluation that is on screen while the save lands', async () => {
    render(<StockEvaluation />, { wrapper })
    expect(await screen.findByText('evaluated with balanced')).toBeInTheDocument()

    await switchToAggressive()

    expect(await screen.findByText('evaluated with aggressive')).toBeInTheDocument()
  })
})
