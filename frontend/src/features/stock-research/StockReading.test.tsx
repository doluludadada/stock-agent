import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import type { Visibilities } from '@/shared/api'
import { siteShowing } from '@/test/features'
import { AnalysisPanel } from './AnalysisPanel'
import type { StockAnalysis, StockNews, StockRanking } from './api'
import { newsText, outboundUrl, shownQuarters } from './model'
import { NewsPanel } from './NewsPanel'
import { StockSummary } from './StockSummary'

const ratio = (latest: number | null, median: number | null, sessions: number) => ({ latest, median, sessions })

const quarter = (year: number, quarterOfYear: number, yearToDate: number | null, own: number | null, change: number | null) => ({
  quarter: { year, quarter: quarterOfYear },
  eps_year_to_date: yearToDate,
  quarter_eps: own,
  eps_year_over_year: change,
  gross_margin: null,
  operating_margin: null,
  net_margin: null,
  debt_ratio: null,
})

const thin: StockAnalysis = {
  revenue: {
    months: [
      { year: 2026, month: 9, revenue: 511_857_399, year_over_year: 0.5465, acceleration: null, served_date: '2026-10-17' },
      { year: 2026, month: 10, revenue: 586_890_319, year_over_year: 0.5971, acceleration: null, served_date: '2026-11-12' },
    ],
    short_months: 3,
    long_months: 12,
    accelerating_months: null,
    growing_months: 2,
  },
  earnings: {
    quarters: [quarter(2025, 2, 30, null, null), quarter(2026, 2, 36, null, 0.2)],
    eps_growing_quarters: 1,
    filed_eps_fetched_at: '2026-10-19T10:00:00+08:00',
  },
  valuation: {
    session_date: '2026-11-12',
    first_session: '2026-11-06',
    sessions: 2,
    min_sessions: 60,
    pe_ratio: ratio(27.12, null, 2),
    pb_ratio: ratio(9.43, null, 2),
    dividend_yield: ratio(0.94, null, 2),
  },
  readings: [
    { kind: 'revenue_history_short', count: 2 },
    { kind: 'revenue_growing', count: 2 },
    { kind: 'eps_up', count: 1 },
    { kind: 'valuation_history_short', count: 2 },
  ],
}

const news: StockNews = {
  stock_id: '2330',
  items: [
    {
      source: 'news_media',
      title: '<img src=x onerror=alert(1)> 台積電法說',
      url: 'https://news.example/a',
      published_at: '2026-11-12T05:01:11Z',
      open_text: null,
      clause: null,
      fact_date: null,
    },
    {
      source: 'ptt_stock',
      title: '[標的] 2330 多',
      url: 'javascript:alert(1)',
      published_at: '2026-11-11T16:00:00Z',
      open_text: null,
      clause: null,
      fact_date: null,
    },
    {
      source: 'twse_mops',
      title: '澄清媒體報導',
      url: null,
      published_at: '2026-11-06T02:05:50Z',
      open_text: '本公司說明如下 <b>粗體</b>',
      clause: '第51款',
      fact_date: '2026-11-06',
    },
  ],
}

const scored: StockRanking = {
  decided_on: '2026-11-13',
  revenue_month: '2026-10-01',
  universe: 1010,
  scored: 987,
  top: 20,
  place: 12,
  score: 98.88,
  in_top: true,
  exclusion: null,
  stock: { stock_id: '2330', stock_name: null, revenue_acceleration: 1.253, nearness_to_high: 0.982, acceleration_rank: 0.92, nearness_rank: 0.78, score: 1.7 },
}

/** Answers the summary's requests: whom the site shows what, the analysis, and the ranking standing or its refusal. */
function renderSummary(ranking: StockRanking | null, hidden: Visibilities = {}) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/v1/auth/status') return new Response(JSON.stringify(siteShowing(hidden)), { status: 200, headers: { 'Content-Type': 'application/json' } })
      const body = url.endsWith('/ranking') ? (ranking ?? { detail: 'No ranking can be made yet.', code: 'ranking_unavailable' }) : thin
      return new Response(JSON.stringify(body), { status: url.endsWith('/ranking') && !ranking ? 422 : 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <StockSummary stockId="2330" />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

function renderWith(body: unknown, element: React.ReactNode, status = 200) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })))
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>{element}</MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('the summary at the top of the page', () => {
  it('shows the score with its place, the two factors’ percentiles, the decision it belongs to and what it measures', async () => {
    renderSummary(scored)
    const score = within(await screen.findByRole('region', { name: 'Ranking score' }))
    expect(await score.findByText('99')).toBeTruthy()
    expect(score.getByText('of 100')).toBeTruthy()
    expect(score.getByText('Place 12 of the 987 stocks scored')).toBeTruthy()
    expect(score.getByText('In the top 20')).toBeTruthy()
    expect(score.getByText('Decided 11/13/2026 on revenue of October 2026')).toBeTruthy()
    expect(score.getByText('PR 92').textContent).toBe('PR 92×1.25')
    expect(score.getByText('PR 78').textContent).toBe('PR 7898.2%')
    expect(score.getByText(/It is no forecast\./)).toBeTruthy()
  })

  it('shows the revenue alone, and never asks for the score, where the site does not show the viewer the ranking', async () => {
    renderSummary(scored, { ranking: 'administrators' })
    expect(await screen.findByRole('region', { name: 'Monthly revenue' })).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Ranking score' })).toBeNull()
    expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual(expect.not.arrayContaining(['/v1/market/stocks/2330/ranking']))
    expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toContain('/v1/auth/status')
  })

  it('gives a stock the ranking leaves out the reason and no number', async () => {
    renderSummary({ ...scored, place: null, score: null, stock: null, in_top: false, exclusion: 'illiquid' })
    const score = within(await screen.findByRole('region', { name: 'Ranking score' }))
    expect(await score.findByText('No score')).toBeTruthy()
    expect(score.getByText('It trades too little for the ranking’s liquid universe.')).toBeTruthy()
    expect(score.queryByText('of 100')).toBeNull()
  })

  it('says there is no score yet while the site holds no decision day, and still shows the revenue', async () => {
    renderSummary(null)
    expect(await screen.findByText('No score yet: the daily history holds no decision day.')).toBeTruthy()
    const revenue = within(screen.getByRole('region', { name: 'Monthly revenue' }))
    expect(await revenue.findByText('Revenue of October 2026')).toBeTruthy()
    expect(revenue.getByText('+59.7%')).toBeTruthy()
    expect(revenue.getByText(/Months held: 2, so no acceleration yet/)).toBeTruthy()
  })
})

describe('the financial analysis', () => {
  it('says how little is held instead of drawing a trend', async () => {
    renderWith(thin, <AnalysisPanel stockId="2330" />)
    const reading = within(await screen.findByRole('region', { name: 'The reading' }))
    expect(reading.getByText('Only 2 months of revenue are held, too few to say whether revenue is accelerating: that needs 12.')).toBeTruthy()
    expect(reading.getByText('Monthly revenue has been above the same month a year before for 2 months in a row.')).toBeTruthy()
    expect(reading.getByText('Year-to-date EPS has been above a year before for 1 quarter.')).toBeTruthy()
    expect(reading.getByText('Only 2 sessions of valuation are held, too few to say whether the P/E is high or low for this stock: that needs 60.')).toBeTruthy()
    expect(reading.getByText('For research and reference only, not investment advice.')).toBeTruthy()
    expect(screen.getAllByText('Sessions held: 2 of the 60 a median needs.')).toHaveLength(3)
    expect(screen.getByText(/Months held: 2, so no acceleration yet/)).toBeTruthy()
  })

  it('shows each figure with its period and the day its source served it', async () => {
    renderWith(thin, <AnalysisPanel stockId="2330" />)
    expect(await screen.findByText('October 2026 · served 11/12/2026')).toBeTruthy()
    expect(screen.getByText('11/12/2026 session')).toBeTruthy()
    const quarters = within(screen.getByRole('table', { name: 'Quarterly earnings' }))
    expect(quarters.getAllByRole('row').map((row) => row.textContent)).toEqual([
      'QuarterQuarter EPSEPS year to dateYear over yearGross marginOperating marginNet margin',
      'Q2 2026—36.00Up +20.0%———',
      'Q2 2025—30.00————',
    ])
  })

  it('says so when the analysis cannot be loaded', async () => {
    renderWith({ detail: 'down', code: 'request_refused' }, <AnalysisPanel stockId="2330" />, 500)
    expect(await screen.findByText('The financial analysis could not be loaded.')).toBeTruthy()
  })
})

describe('the news', () => {
  it('renders third-party titles and text as text, and links only to http addresses', async () => {
    renderWith(news, <NewsPanel stockId="2330" />)
    const list = within(await screen.findByRole('list'))
    expect(list.getByText('<img src=x onerror=alert(1)> 台積電法說')).toBeTruthy()
    expect(list.getByText('本公司說明如下 <b>粗體</b>')).toBeTruthy()
    expect(document.querySelector('#stock-news img, #stock-news b')).toBeNull()
    const links = list.getAllByRole('link')
    expect(links.map((link) => [link.getAttribute('href'), link.getAttribute('rel'), link.getAttribute('target')])).toEqual([
      ['https://news.example/a', 'noopener noreferrer nofollow', '_blank'],
    ])
  })

  it('times an article in Taipei and dates a board post by its day', async () => {
    renderWith(news, <NewsPanel stockId="2330" />)
    const items = (await screen.findAllByRole('listitem')).map((item) => item.querySelector('time')?.textContent)
    expect(items).toEqual(['11/12, 13:01', '11/12/2026', '11/6, 10:05'])
  })

  it('says so when nothing is held', async () => {
    renderWith({ stock_id: '6898', items: [] }, <NewsPanel stockId="6898" />)
    expect(await screen.findByText('Nothing recent about this stock')).toBeTruthy()
  })
})

describe('the model', () => {
  it('links out only to http and https addresses', () => {
    expect(outboundUrl('https://www.ptt.cc/bbs/Stock/M.1.html')).toBe('https://www.ptt.cc/bbs/Stock/M.1.html')
    expect(['javascript:alert(1)', 'data:text/html,x', '/relative', '', null].map(outboundUrl)).toEqual([null, null, null, null, null])
  })

  it('drops an open text that only repeats the title', () => {
    const item = news.items[2]!
    expect(newsText({ ...item, open_text: ' 澄清媒體報導 ' })).toBeNull()
    expect(newsText(item)).toBe('本公司說明如下 <b>粗體</b>')
  })

  it('lists the quarters that hold a figure, newest first', () => {
    const quarters = [quarter(2025, 4, 40, null, null), quarter(2026, 1, null, null, null), quarter(2026, 2, 25, null, null)]
    expect(shownQuarters(quarters).map((result) => result.quarter)).toEqual([
      { year: 2026, quarter: 2 },
      { year: 2025, quarter: 4 },
    ])
  })
})
