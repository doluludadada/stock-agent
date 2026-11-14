import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter, useLocation } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { OPEN_SITE } from '@/test/features'
import { TEST_USER } from '@/test/users'
import { StockResearchPage } from './StockResearchPage'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function wrap(page: ReactNode) {
  return (
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>{page}</MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>
  )
}

function Address() {
  return <p>at {useLocation().pathname}</p>
}

const NEEDS_SIGN_IN = /\/(news|technical)$/

/** The server's gates on the stock page: news, the technical evaluation and a brief's writing answer 401 without a session. */
function gatedBackend(viewer: 'visitor' | 'user') {
  const bars = ['2026-11-11', '2026-11-12'].map((day) => ({ ts: `${day}T13:30:00+08:00`, open: 2250, high: 2285, low: 2235, close: 2240, volume: 45_175_145, change: null }))
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const gated = NEEDS_SIGN_IN.test(url) || init?.method === 'POST'
    if (gated && viewer === 'visitor') return json({ detail: 'Sign in first.', code: 'unauthorized' }, 401)
    if (url.startsWith('/v1/market/stocks/2330?')) return json({ stock: { stock_id: '2330', name: 'TSMC', market: 'twse', today: null }, bars, notes: [] })
    if (url === '/v1/auth/status') return json(OPEN_SITE)
    if (url === '/v1/market/audience') return json(PERSONAL_SITE)
    if (url === '/v1/market/stocks/2330/brief') return json({ stock_id: '2330', today: null, previous: null, stocks_left: 5 })
    if (url === '/v1/market/stocks/2330/news') {
      return json({ stock_id: '2330', items: [{ source: 'twse_news', published_at: '2026-11-12T09:00:00+08:00', title: 'TSMC reports October revenue', url: null, clause: null, fact_date: null, open_text: null }] })
    }
    return json({ detail: 'not held', code: 'not_found' }, 404)
  })
  vi.stubGlobal('fetch', fetch)
  const asked = () => fetch.mock.calls.map(([url, init]) => `${init?.method ?? 'GET'} ${url}`)
  return { asked, gatedAsked: () => asked().filter((call) => NEEDS_SIGN_IN.test(call) || call.startsWith('POST')) }
}

function renderStockPage() {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  render(
    wrap(
      <>
        <StockResearchPage code="2330" strategyName={(strategy) => strategy.name} ruleName={(_strategy, name) => name} />
        <Address />
      </>,
    ),
  )
}

describe('the stock page', () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('asks a visitor’s server for nothing that needs a sign-in, says the news needs one, and leaves the visitor where they are', async () => {
    session.signOut()
    const backend = gatedBackend('visitor')
    renderStockPage()

    await screen.findByText('No brief has been written today')
    await screen.findByRole('region', { name: 'Ranking score' })
    await waitFor(() => expect(backend.asked()).toContain('GET /v1/market/stocks/2330/analysis'))
    expect(backend.gatedAsked()).toEqual([])
    const news = screen.getByRole('region', { name: 'News and discussion' })
    expect(await within(news).findByText('Sign in to read the news and discussion')).toBeInTheDocument()
    expect(screen.queryByText('The news could not be loaded.')).not.toBeInTheDocument()
    expect(session.current()).toEqual({ status: 'signedOut', ended: false })
    expect(screen.getByText('at /')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'TSMC' })).toBeInTheDocument()
  })

  it('still asks for the news of a signed-in viewer and shows it', async () => {
    session.signIn(TEST_USER)
    const backend = gatedBackend('user')
    renderStockPage()

    const news = await screen.findByRole('region', { name: 'News and discussion' })
    expect(await within(news).findByText('TSMC reports October revenue')).toBeInTheDocument()
    expect(backend.asked()).toContain('GET /v1/market/stocks/2330/news')
    expect(within(news).queryByText('Sign in to read the news and discussion')).not.toBeInTheDocument()
  })

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

  it('reads revenue and score first, then the company, the AI brief and the news, then the chart and the tables', async () => {
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
      'Company',
      'AI brief',
      'News and discussion',
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
