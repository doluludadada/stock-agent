import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
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
      return json({})
    })
    vi.stubGlobal('fetch', fetch)
    render(wrap(<StockResearchPage code="4523" strategyName={(strategy) => strategy.name} ruleName={(_strategy, name) => name} />))

    expect(await screen.findByText('No daily bars for this stock yet.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Yung Chang' })).toBeInTheDocument()
    expect(screen.queryByText('Price and volume')).not.toBeInTheDocument()
    expect(fetch.mock.calls.map(([url]) => url).filter((url) => url.includes('/technical'))).toEqual([])
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
