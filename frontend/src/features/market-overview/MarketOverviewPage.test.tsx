import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import type { Audience, Schemas } from '@/shared/api'
import { PERSONAL_SITE, PUBLIC_SITE } from '@/test/audiences'
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

async function renderOverview(site: Audience = PERSONAL_SITE) {
  const answers: Record<string, unknown> = {
    '/v1/market/indexes/taiex': taiex,
    '/v1/market/most-traded': [],
    '/v1/market/breadth': breadth,
    '/v1/market/audience': site,
    '/v1/market/archive-status': { sessions: 2, needed: 61 },
  }
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

  it('says on a public site how far the archive its history comes from has come, and nothing of it on the owner’s site', async () => {
    await renderOverview(PUBLIC_SITE)
    const warmUp = await screen.findByRole('region', { name: 'Open-data archive' })

    expect(warmUp.textContent).toContain('Data accumulating 2/61')
    expect(within(warmUp).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '2')
  })

  it('shows no warm-up on the owner’s site', async () => {
    await renderOverview(PERSONAL_SITE)

    expect(screen.queryByRole('region', { name: 'Open-data archive' })).not.toBeInTheDocument()
  })

  it('shows the session counts in one phrase, colored by direction', async () => {
    await renderOverview()
    const panel = screen.getByRole('region', { name: 'Advancers and decliners' })

    expect(within(panel).getByText('Broadly down')).toHaveClass('text-down')
    expect(within(panel).getByText('312')).toHaveClass('text-up')
    expect(within(panel).getByText('1,488')).toHaveClass('text-down')
  })

  it('names both ends of the industries by their sign, and lists all of them on request', async () => {
    await renderOverview()
    const panel = screen.getByRole('region', { name: 'Industries' })
    const table = within(panel).getByRole('table', { name: 'Industries' })
    const shown = () => within(table).getAllByRole('row').slice(1).map((row) => row.querySelector('td, th')?.textContent)

    expect(shown()).toEqual(['Largest gains', 'Industry A', 'Industry B', 'Industry C', 'Largest declines', 'Industry H', 'Industry I', 'Industry J'])

    await userEvent.setup().click(within(panel).getByRole('button', { name: 'Show all 10 industries' }))

    expect(shown()).toEqual(Object.keys(industries))
  })
})
