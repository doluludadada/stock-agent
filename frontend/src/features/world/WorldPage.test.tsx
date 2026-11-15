import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import openapi from '@/shared/api/openapi.json'
import { TEST_USER } from '@/test/users'
import { briefState, citedSources, clockTime, eventSentences, INDICATORS, newsSources, shownNews, type World, type WorldBrief, type WorldNews } from './model'
import { WorldPage } from './WorldPage'
import { WorldToday } from './WorldToday'

const EXPORT_CONTROLS: WorldNews = {
  source: 'cna',
  title: '美擴大晶片出口管制 台積電稱影響有限',
  url: 'https://www.cna.com.tw/news/aopl/1.aspx',
  published_at: '2026-11-13T21:05:00Z',
  open_text: '（中央社華盛頓13日電）美國商務部宣布擴大管制。',
  clause: null,
  fact_date: null,
}
const RATE_CUT: WorldNews = { source: 'bbc', title: 'Fed cuts rates by a quarter point', url: 'https://www.bbc.co.uk/news/articles/2', published_at: '2026-11-13T19:00:00Z', open_text: 'Fed cuts rates by a quarter point', clause: null, fact_date: null }
const MARKED_UP: WorldNews = { source: 'bbc', title: '<img src=x onerror=alert(1)> Oil rises', url: 'javascript:alert(1)', published_at: '2026-11-13T18:00:00Z', open_text: null, clause: null, fact_date: null }

const BRIEF: WorldBrief = {
  stock_id: '#world',
  day: '2026-11-14',
  status: 'written',
  language: 'zh-TW',
  model: 'claude-haiku-5-5',
  claimed_at: '2026-11-13T23:31:00Z',
  written_at: '2026-11-13T23:31:20Z',
  window_first: '2026-11-13',
  window_last: '2026-11-14',
  price_change: null,
  company: [],
  movement: [
    { text: '美元兌新台幣收 32.838，較前一日上升 0.12%。', sources: ['S1'], stocks: [] },
    { text: '美國擴大晶片出口管制，可能與半導體類股有關。', sources: ['S3', 'S9'], stocks: ['2330'] },
  ],
  sources: [
    { key: 'S1', kind: 'indicator', dated: '2026-11-13', title: null, url: null, origin: null },
    { key: 'S3', kind: 'world_news', dated: '2026-11-14', title: EXPORT_CONTROLS.title, url: EXPORT_CONTROLS.url, origin: 'cna' },
  ],
  fingerprint: null,
}
const THE_DAY_BEFORE: WorldBrief = { ...BRIEF, day: '2026-11-13', movement: [{ text: '前一日的摘要。', sources: ['S1'], stocks: [] }] }

const HELD: World = {
  indicators: [
    { indicator: 'usd_twd', day: '2026-11-13', value: 32.838, previous_day: '2026-11-12', previous: 32.8, change: 0.00116 },
    { indicator: 'us_10y_yield', day: '2026-11-13', value: 5.15, previous_day: '2026-11-12', previous: 5.1, change: 0.05 },
  ],
  briefs: [BRIEF, THE_DAY_BEFORE],
  news: [EXPORT_CONTROLS, RATE_CUT, MARKED_UP],
  write_at: '07:30:00',
}
const NOTHING_HELD: World = { indicators: [], briefs: [], news: [], write_at: '07:30:00' }

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function serve(world: () => Response) {
  const asked: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const { pathname, searchParams } = new URL(url, 'http://localhost')
      asked.push(pathname)
      if (pathname === '/v1/world') return world()
      if (pathname === '/v1/market/stocks') return json(searchParams.get('query') === '2330' ? [{ stock_id: '2330', name: '台積電', market: 'twse', today: null }] : [])
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  return asked
}

function open(page: 'page' | 'today' = 'page') {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>{page === 'page' ? <WorldPage /> : <WorldToday />}</MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the world as the site holds it', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('knows how to write every indicator of the contract', () => {
    expect(Object.keys(INDICATORS).sort()).toEqual([...(openapi.components.schemas.WorldIndicator.enum as string[])].sort())
  })

  it('reads a brief’s citations, the publishers and what a card says from the answer alone', () => {
    expect(citedSources(BRIEF.movement![1]!, BRIEF).map((source) => source.key), 'a key the brief does not hold names nothing').toEqual(['S3'])
    expect(newsSources(HELD.news)).toEqual(['cna', 'bbc'])
    expect(shownNews(HELD.news, 'bbc')).toEqual([RATE_CUT, MARKED_UP])
    expect(eventSentences(BRIEF), 'the sentence that cites only an indicator is the strip’s').toEqual([BRIEF.movement![1]])
    expect(eventSentences(THE_DAY_BEFORE)).toEqual(THE_DAY_BEFORE.movement)
    expect(clockTime('07:30:00')).toBe('07:30')
    expect(briefState(HELD, 1)).toEqual({ kind: 'written', brief: THE_DAY_BEFORE })
    expect(briefState(NOTHING_HELD)).toEqual({ kind: 'waiting', writeAt: '07:30' })
    expect(briefState({ ...NOTHING_HELD, write_at: null })).toEqual({ kind: 'off' })
  })

  it('shows the indicators, the brief with what each sentence cites, and the news by publisher', async () => {
    serve(() => json(HELD))
    open()

    const indicators = within(await screen.findByRole('region', { name: 'Indicators' }))
    expect(indicators.getByText('32.838')).toBeInTheDocument()
    expect(indicators.getByText('+0.12%')).toBeInTheDocument()
    expect(indicators.getByText('5.15%')).toBeInTheDocument()
    expect(indicators.getByText('+0.05')).toBeInTheDocument()

    const brief = within(screen.getByRole('region', { name: 'World brief' }))
    expect(brief.getByText('AI-generated, may be wrong')).toBeInTheDocument()
    expect(brief.getByText('claude-haiku-5-5')).toBeInTheDocument()
    expect(brief.getByText('美國擴大晶片出口管制，可能與半導體類股有關。')).toBeInTheDocument()
    expect(brief.getByRole('link', { name: /CNA · 11\/14 美擴大晶片出口管制/ })).toHaveAttribute('href', EXPORT_CONTROLS.url)
    expect(brief.getByText('Indicator · 11/13')).toBeInTheDocument()
    expect(await brief.findByRole('link', { name: '台積電2330' })).toHaveAttribute('href', '/stocks/2330')
    expect(brief.getByText(/not investment advice/i)).toBeInTheDocument()

    const news = within(screen.getByRole('region', { name: 'World news' }))
    expect(news.getAllByRole('listitem')).toHaveLength(3)
    expect(news.queryByText(EXPORT_CONTROLS.open_text!), 'a title leads to its article; the list repeats no summary').not.toBeInTheDocument()
    await userEvent.click(news.getByRole('radio', { name: 'BBC' }))
    expect(news.getAllByRole('listitem')).toHaveLength(2)
    expect(news.queryByText(EXPORT_CONTROLS.title)).not.toBeInTheDocument()
  })

  it('renders a third party’s title as text and links only a web address', async () => {
    serve(() => json(HELD))
    open()

    const news = within(await screen.findByRole('region', { name: 'World news' }))
    expect(news.getByText('<img src=x onerror=alert(1)> Oil rises')).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    expect(news.queryByRole('link', { name: /Oil rises/ })).not.toBeInTheDocument()
  })

  it('steps back to an earlier day’s brief and forward again', async () => {
    serve(() => json(HELD))
    open()

    const brief = within(await screen.findByRole('region', { name: 'World brief' }))
    expect(brief.getByRole('button', { name: 'Later brief' })).toBeDisabled()
    await userEvent.click(brief.getByRole('button', { name: 'Earlier brief' }))
    expect(brief.getByText('前一日的摘要。')).toBeInTheDocument()
    expect(brief.getByRole('button', { name: 'Earlier brief' })).toBeDisabled()
    await userEvent.click(brief.getByRole('button', { name: 'Later brief' }))
    expect(brief.getByText('美元兌新台幣收 32.838，較前一日上升 0.12%。')).toBeInTheDocument()
  })

  it('says when nothing is held yet, and that a site writes no brief', async () => {
    serve(() => json(NOTHING_HELD))
    open()

    expect(await screen.findByText('No indicator is held yet.')).toBeInTheDocument()
    expect(screen.getByText('No world brief yet')).toBeInTheDocument()
    expect(screen.getByText('One a day, written from 07:30 Taipei.')).toBeInTheDocument()
    expect(screen.getByText('No world news is held yet')).toBeInTheDocument()
  })

  it('says that this site writes no world brief where its own writing is off', async () => {
    serve(() => json({ ...NOTHING_HELD, write_at: null }))
    open()

    expect(await screen.findByText('This site writes no world brief')).toBeInTheDocument()
  })

  it('shows the failure with a way to ask again', async () => {
    serve(() => json({ detail: 'The server failed.', code: 'server_error' }, 500))
    open()

    expect(await screen.findByText('The world could not be loaded.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /again/i })).toBeInTheDocument()
  })

  it('asks a visitor to sign in and asks the server nothing', () => {
    session.signOut()
    const asked = serve(() => json(HELD))
    open()

    expect(screen.getByText('Sign in to read the world brief and news')).toBeInTheDocument()
    expect(asked).toEqual([])
  })

  it('gives the home page the indicators, the brief’s first sentences and the way to the page', async () => {
    serve(() => json({ ...HELD, briefs: [{ ...BRIEF, movement: [...BRIEF.movement!, ...BRIEF.movement!] }] }))
    open('today')

    const card = within(await screen.findByRole('region', { name: 'World' }))
    expect(await card.findByText('USD/TWD')).toBeInTheDocument()
    expect(card.getAllByRole('listitem'), 'the two sentences about events, not the indicators’').toHaveLength(2)
    expect(card.getByText('AI-generated, may be wrong')).toBeInTheDocument()
    expect(card.getByRole('link', { name: 'Brief and news' })).toHaveAttribute('href', '/world')
    expect(card.queryByRole('link', { name: /CNA/ }), 'the card leaves the citations to the page').not.toBeInTheDocument()
  })

  it('says on the home page when the day’s brief is written, while the site holds none', async () => {
    serve(() => json({ ...HELD, briefs: [] }))
    open('today')

    const card = within(await screen.findByRole('region', { name: 'World' }))
    expect(await card.findByText('USD/TWD')).toBeInTheDocument()
    expect(card.getByText('One a day, written from 07:30 Taipei.')).toBeInTheDocument()
  })
})
