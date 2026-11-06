import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { StockResearchPage } from './StockResearchPage'

describe('the stock page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says a code that cannot be a stock id is not a listed stock, without asking the server', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ detail: [{ loc: ['path', 'stock_id'], msg: 'bad' }] }), { status: 422 }))
    vi.stubGlobal('fetch', fetch)
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <StockResearchPage code="23-30" strategyName={(strategy) => strategy.name} ruleName={(name) => name} />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>,
    )

    expect(await screen.findByText('No listed stock with code 23-30')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })
})
