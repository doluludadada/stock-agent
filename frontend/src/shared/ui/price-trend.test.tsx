import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import type { Audience, DailyBar } from '@/shared/api'
import { PERSONAL_SITE, PUBLIC_SITE } from '@/test/audiences'
import { PriceTrend } from './price-trend'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
const sessions = (days: string[]): DailyBar[] =>
  days.map((day) => ({ ts: `${day}T13:30:00+08:00`, open: 2250, high: 2285, low: 2235, close: 2240, volume: 45_175_145, change: null }))

function open(audience: Audience, bars: DailyBar[], warmUp = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/v1/market/audience') return json(audience)
      if (url === '/v1/market/archive-status') return json({ sessions: 2, needed: 61 })
      return json([])
    }),
  )
  const { container } = render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <PriceTrend bars={bars} name="TSMC" kind="price" quote={false} warmUp={warmUp} />
      </QueryClientProvider>
    </I18nextProvider>,
  )
  return container
}

describe('a price trend with too few sessions to draw a line', () => {
  beforeAll(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }))
  afterAll(() => vi.unstubAllGlobals())

  it('says in the chart’s place how far a public site’s archive has come', async () => {
    const chart = open(PUBLIC_SITE, sessions(['2026-11-05']))

    expect(await screen.findByRole('progressbar', { name: 'Open-data archive' })).toHaveAttribute('aria-valuenow', '2')
    expect(screen.getByText('2/61')).toBeVisible()
    expect(chart.querySelector('.recharts-responsive-container')).toBeNull()
  })

  it('says it needs a second session on a site with every source', async () => {
    const chart = open(PERSONAL_SITE, sessions(['2026-11-05']))

    expect(await screen.findByText('One session so far: the chart draws from the second.')).toBeVisible()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(chart.querySelector('.recharts-responsive-container')).toBeNull()
  })

  it('leaves the archive’s progress to a page that shows it above the chart', async () => {
    open(PUBLIC_SITE, sessions(['2026-11-05']), false)

    expect(await screen.findByText('One session so far: the chart draws from the second.')).toBeVisible()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('draws the sessions there are once there are two, while the archive still fills', async () => {
    const chart = open(PUBLIC_SITE, sessions(['2026-11-05', '2026-11-06']))

    await vi.waitFor(() => expect(chart.querySelector('.recharts-responsive-container')).not.toBeNull())
    expect(screen.queryByText('One session so far: the chart draws from the second.')).not.toBeInTheDocument()
  })
})
