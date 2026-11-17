import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import type { ReactNode } from 'react'
import { session, type Audience, type Schemas } from '@/shared/api'
import { PERSONAL_SITE, PUBLIC_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { MarketOverviewPage } from './MarketOverviewPage'
import { MarketToday } from './MarketToday'

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

/** The session after the settled ones, so far: the TAIEX up 180.36 at 10:32:05. */
const quoted: Schemas['PageQuotesResponse'] = {
  realtime_quotes: true,
  refresh: { changing: true, seconds: 10 },
  quotes: {},
  indexes: { taiex: { ts: '2026-11-04T10:32:05+08:00', open: 44980.2, high: 45120.6, low: 44910.3, close: 45100.5, volume: 0, change: 180.36 } },
}
const INDEX_QUOTES = '/v1/market/index-quotes'

function renderWith(page: ReactNode, site: Audience, quotes: Schemas['PageQuotesResponse'] | 'refused' | null, address = '/market') {
  const answers: Record<string, unknown> = {
    '/v1/market/indexes/taiex': taiex,
    '/v1/market/most-traded': [],
    '/v1/market/breadth': breadth,
    '/v1/market/audience': site,
    '/v1/market/archive-status': { sessions: 2, needed: 61 },
  }
  const asked: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input instanceof Request ? input.url : input)
    const path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0]!
    asked.push(path)
    const refused = path === INDEX_QUOTES && quotes === 'refused'
    const body = refused ? { detail: 'Hidden.', code: 'feature_hidden' } : path === INDEX_QUOTES ? quotes : answers[path]
    return new Response(JSON.stringify(body), { status: refused ? 403 : 200, headers: { 'Content-Type': 'application/json' } })
  }))
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={[address]}>{page}</MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
  return asked
}

async function renderOverview(site: Audience = PERSONAL_SITE) {
  renderWith(<MarketOverviewPage />, site, null)
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

  it.each([
    ['with', PERSONAL_SITE],
    ['without', { ...PERSONAL_SITE, realtime_quotes: false }],
  ])('shows no warm-up on the owner’s site %s a Shioaji login, whose history comes from the exchanges’ reports', async (_, audience) => {
    await renderOverview(audience)

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

describe('the market overview once a session opened', () => {
  beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('ends the TAIEX at its quote with the live mark and its time for a signed-in viewer, and keeps the settled breadth', async () => {
    session.signIn(TEST_USER)
    renderWith(<MarketOverviewPage />, PERSONAL_SITE, quoted)

    const trend = screen.getByRole('region', { name: /TAIEX/ })
    expect(await within(trend).findByText('45,100.50')).toBeVisible()
    expect(within(trend).getByText(/\+180\.36/)).toBeVisible()
    expect(within(trend).getByText(/\+0\.40%/)).toBeVisible()
    expect(within(trend).getByTestId('quote-time')).toHaveTextContent('Live 10:32')
    expect(within(trend).queryByText(/11\/2/)).toBeNull()
    expect(within(trend).getByText('Volume').nextElementSibling).toHaveTextContent('—')
    const split = screen.getByRole('region', { name: 'Advancers and decliners' })
    expect(await within(split).findByText('312')).toBeVisible()
    expect(within(split).queryByTestId('quote-time')).toBeNull()
  })

  it('asks for no index quote while the trend shows a stock', async () => {
    session.signIn(TEST_USER)
    const asked = renderWith(<MarketOverviewPage />, PERSONAL_SITE, quoted, '/market?target=2330')

    expect(await screen.findByText('312')).toBeVisible()
    await waitFor(() => expect(asked).toContain('/v1/market/audience'))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(asked).not.toContain(INDEX_QUOTES)
  })

  it('shows the quote in the home page’s headline, beside the settled breadth', async () => {
    session.signIn(TEST_USER)
    renderWith(<MarketToday />, PERSONAL_SITE, quoted)

    expect(await screen.findByText('45,100.50')).toBeVisible()
    expect(screen.getByText(/\+180\.36/)).toBeVisible()
    expect(screen.getByTestId('quote-time')).toHaveTextContent('Live 10:32')
    expect(await screen.findByText(/312/)).toBeVisible()
  })

  it.each([
    ['a visitor', false, PERSONAL_SITE, quoted, false],
    ['a site without realtime quotes', true, { ...PERSONAL_SITE, realtime_quotes: false }, quoted, false],
    ['a viewer the site refuses the index', true, PERSONAL_SITE, 'refused' as const, true],
    ['the opening call auction', true, PERSONAL_SITE, { ...quoted, refresh: { changing: true, seconds: 10 }, indexes: { taiex: null } }, true],
    ['a session that is over with nothing read', true, PERSONAL_SITE, { ...quoted, refresh: { changing: false, seconds: 300 }, indexes: { taiex: null } }, true],
  ])('stays on the settled close for %s', async (_, signedIn, site, quotes, asks) => {
    if (signedIn) session.signIn(TEST_USER)
    const asked = renderWith(<MarketToday />, site, quotes)

    expect(await screen.findByText('44,920.14')).toBeVisible()
    expect(await screen.findByText(/312/)).toBeVisible()
    expect(screen.getByText(/11\/2 close/)).toBeVisible()
    expect(screen.queryByTestId('quote-time')).toBeNull()
    expect(asked.includes(INDEX_QUOTES)).toBe(asks)
  })
})
