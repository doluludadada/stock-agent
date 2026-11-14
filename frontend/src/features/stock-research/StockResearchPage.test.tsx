import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { PERSONAL_SITE } from '@/test/audiences'
import { OPEN_SITE } from '@/test/features'
import { StockResearchPage } from './StockResearchPage'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

function wrap(page: ReactNode) {
  return (
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>{page}</MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>
  )
}

describe('the stock page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says in one line that a listed stock has no daily bars yet, as while the history fills, and evaluates nothing', async () => {
    const fetch = vi.fn(async (url: string) => {
      if (url.startsWith('/v1/market/stocks/4523?')) {
        return json({ stock: { stock_id: '4523', name: 'Yung Chang', market: 'tpex', today: null }, bars: [], notes: [] })
      }
      if (url === '/v1/market/stocks/4523/financials') return json({ stock_id: '4523', quarters: [], monthly_revenues: [] })
      if (/\/(analysis|news|ranking)$/.test(url)) return new Response(JSON.stringify({ detail: 'not held', code: 'not_found' }), { status: 404 })
      return json({})
    })
    vi.stubGlobal('fetch', fetch)
    render(wrap(<StockResearchPage code="4523" strategyName={(strategy) => strategy.name} ruleName={(_strategy, name) => name} />))

    expect(await screen.findByText('No daily bars for this stock yet.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Yung Chang' })).toBeInTheDocument()
    expect(screen.queryByText('Price and volume')).not.toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => url).filter((url) => url.includes('/technical'))).toEqual([])
  })

  it('reads revenue and score first, then the AI brief and the news, then the chart and the tables', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const bars = ['2026-11-11', '2026-11-12'].map((day) => ({ ts: `${day}T13:30:00+08:00`, open: 2250, high: 2285, low: 2235, close: 2240, volume: 45_175_145, change: null }))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.startsWith('/v1/market/stocks/2330?')) return json({ stock: { stock_id: '2330', name: 'TSMC', market: 'twse', today: null }, bars, notes: [] })
        if (url === '/v1/auth/status') return json(OPEN_SITE)
        if (url === '/v1/market/audience') return json(PERSONAL_SITE)
        if (url === '/v1/market/stocks/2330/brief') return json({ stock_id: '2330', today: null, previous: null, stocks_left: 5 })
        return new Response(JSON.stringify({ detail: 'not held', code: 'not_found' }), { status: 404 })
      }),
    )
    render(wrap(<StockResearchPage code="2330" strategyName={(strategy) => strategy.name} ruleName={(_strategy, name) => name} />))

    await screen.findByText('No brief has been written today')
    await screen.findByRole('region', { name: 'Ranking score' })
    expect(screen.getAllByRole('region').map((region) => region.getAttribute('aria-labelledby') && region.querySelector('h2')?.textContent).filter(Boolean).slice(0, 5)).toEqual([
      'Ranking score',
      'Monthly revenue',
      'AI brief',
      'News and discussion',
      'Price and volume',
    ])
  })

  it('says a code that cannot be a stock id is not a listed stock, without asking the server', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ detail: [{ loc: ['path', 'stock_id'], msg: 'bad' }] }), { status: 422 }))
    vi.stubGlobal('fetch', fetch)
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <StockResearchPage code="23-30" strategyName={(strategy) => strategy.name} ruleName={(_strategy, name) => name} />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>,
    )

    expect(await screen.findByText('No listed stock with code 23-30')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })
})
