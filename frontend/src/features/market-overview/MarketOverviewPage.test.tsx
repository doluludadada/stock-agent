import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import type { Schemas } from '@/shared/api'
import { MarketOverviewPage } from './MarketOverviewPage'

const industries = Object.fromEntries(
  ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'].map((name, rank) => [
    `Industry ${name}`,
    { advancers: 10 - rank, decliners: rank, unchanged: 1, average_change_percent: 5 - rank },
  ]),
)
const breadth: Schemas['MarketBreadth'] = {
  session_close: '2026-11-03T13:30:00+08:00',
  market: { advancers: 312, decliners: 1488, unchanged: 96, average_change_percent: -2.41 },
  industries,
}
const taiex: Schemas['IndexHistoryResponse'] = {
  index: 'taiex',
  bars: [
    { ts: '2026-10-30T13:30:00+08:00', open: 46139.79, high: 46139.79, low: 44726.26, close: 45211.83, volume: 4001100, change: null },
    { ts: '2026-11-02T13:30:00+08:00', open: 45034.53, high: 45156.17, low: 44399.1, close: 44920.14, volume: 3232000, change: null },
  ],
}

async function renderOverview() {
  const answers: Record<string, unknown> = { '/v1/market/indexes/taiex': taiex, '/v1/market/most-traded': [], '/v1/market/breadth': breadth }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(answers[url.split('?')[0]!]), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <MarketOverviewPage strategy={null} />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
  await screen.findByText('44,920.14')
  await screen.findByText('312')
}

describe('the market overview', () => {
  beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }))
  afterEach(() => vi.unstubAllGlobals())

  it('charts the TAIEX as the default index, not as a stock', async () => {
    await renderOverview()

    const trend = screen.getByRole('region', { name: /TAIEX/ })
    expect(within(trend).getByRole('heading', { level: 2 })).toHaveTextContent('TAIEXIndex · Default')
    expect(within(trend).getByText('44,920.14')).toBeVisible()
    expect(within(trend).queryByRole('link', { name: /TAIEX/ })).toBeNull()
  })

  it('shows the session counts and the strongest and weakest industries, and all of them on request', async () => {
    await renderOverview()
    const panel = screen.getByRole('region', { name: 'Market breadth' })

    expect(within(panel).getByText('312')).toHaveClass('text-up')
    expect(within(panel).getByText('1,488')).toHaveClass('text-down')
    const shown = () => within(panel).getAllByRole('row').slice(1).map((row) => row.textContent ?? '')
    expect(shown().filter((text) => text.startsWith('Industry')).map((text) => text.slice(0, 10))).toEqual([
      'Industry A', 'Industry B', 'Industry C', 'Industry D', 'Industry G', 'Industry H', 'Industry I', 'Industry J',
    ])

    await userEvent.setup().click(within(panel).getByRole('button', { name: 'Show all 10 industries' }))

    expect(shown().map((text) => text.slice(0, 10))).toEqual(Object.keys(industries))
  })
})
