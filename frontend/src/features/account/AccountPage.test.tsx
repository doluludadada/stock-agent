import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type Schemas } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { AccountPage } from './AccountPage'

const unpriced = { stock_id: '2330', quantity: 1000, average_cost: 100, mark_price: 100, marked_at: null, market_value: 100_000, unrealized_pnl: 0 }
const value = { cash: 900_000, market_value: 100_000, unrealized_pnl: 0, equity: 1_000_000, positions: [unpriced] }
const history: Schemas['AccountHistoryResponse'] = {
  current: value,
  live_stock_ids: [],
  equity_curve: {},
  as_of: null,
  execution_provider: 'mock',
  order_mode: 'mock_only',
}

describe('the account positions', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('says a position without a quote is unpriced, and does not also call it a daily close', async () => {
    const listing = [{ stock_id: '2330', name: '台積電', market: 'twse', today: null }]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => new Response(JSON.stringify(url.startsWith('/v1/market/stocks') ? listing : history), { status: 200, headers: { 'Content-Type': 'application/json' } })),
    )
    session.signIn(TEST_USER)
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <AccountPage />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>,
    )

    const cell = await screen.findByText(/no quote, at average cost/)
    expect(cell).toHaveTextContent(/^no quote, at average cost$/)
  })
})
