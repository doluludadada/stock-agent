import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n, type Locale } from '@/i18n'
import { session } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { BRIEF_POLL_MS } from './api'
import type { StockBrief, StockBriefAnswer, StockCompanyAnswer } from './brief'
import { BriefPanel } from './BriefPanel'

const written: StockBrief = {
  stock_id: '2330',
  day: '2026-11-13',
  status: 'written',
  language: 'en',
  model: 'claude-test-1',
  claimed_at: '2026-11-13T01:00:00Z',
  written_at: '2026-11-13T01:00:20Z',
  window_first: '2026-10-16',
  window_last: '2026-11-12',
  price_change: 0.12,
  company: [{ text: 'It makes chips for other firms.', sources: ['S1'] }],
  movement: [
    { text: 'Revenue grew <b>fast</b>, see [the report](https://evil.example).', sources: ['S3', 'S9'] },
    { text: 'A report named new orders.', sources: ['S4', 'S5'] },
  ],
  sources: [
    { key: 'S1', kind: 'company', dated: '2026-11-13', title: null, url: null },
    { key: 'S2', kind: 'price', dated: '2026-11-12', title: null, url: null },
    { key: 'S3', kind: 'revenue', dated: '2026-11-10', title: null, url: null },
    { key: 'S4', kind: 'news', dated: '2026-11-11', title: 'Orders <i>rise</i>', url: 'https://news.example/a' },
    { key: 'S5', kind: 'post', dated: '2026-11-09', title: '[標的] 2330', url: 'javascript:alert(1)' },
  ],
}

const earlier: StockBrief = { ...written, day: '2026-11-12', written_at: '2026-11-12T02:00:00Z', company: [{ text: 'Yesterday’s words.', sources: ['S1'] }], movement: [] }
const today = (status: StockBrief['status']): StockBrief => ({ ...written, status, written_at: null, company: [], movement: [], sources: [] })
const answer = (parts: Partial<StockBriefAnswer>): StockBriefAnswer => ({ stock_id: '2330', today: null, previous: null, stocks_left: 5, ...parts })

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const nothingHeld: StockCompanyAnswer = { stock_id: '2330', profile: null, sources: [], today: null, previous: null }

/**
 * A backend that answers each GET of the brief with the next of `held` (the last one from then on) and a POST with
 * `posted`. The company is what `company` holds when it is asked, and the site is a personal one.
 */
function backend(held: StockBriefAnswer[], posted: () => Response = () => json(answer({ today: written })), company = { held: nothingHeld }) {
  const calls = { get: 0, post: 0 }
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/v1/market/audience') return json(PERSONAL_SITE)
    if (url === '/v1/market/stocks/2330/company') return json(company.held)
    expect(url).toBe('/v1/market/stocks/2330/brief')
    if (init?.method === 'POST') {
      expect(JSON.parse(String(init.body))).toEqual({ confirm: true })
      calls.post += 1
      return posted()
    }
    calls.get += 1
    return json(held[Math.min(calls.get, held.length) - 1])
  })
  vi.stubGlobal('fetch', fetch)
  return calls
}

function renderPanel(locale: Locale = 'en') {
  const i18n = initI18n('en')
  void i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <BriefPanel stockId="2330" />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('a stock’s AI brief', () => {
  beforeEach(() => session.signOut())
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('shows a written brief with its AI label, model, time, window and each sentence’s citations', async () => {
    backend([answer({ today: written })])
    renderPanel()

    const panel = within(await screen.findByRole('region', { name: 'AI brief' }))
    expect(await panel.findByText('AI-generated, may be wrong')).toBeInTheDocument()
    expect(panel.getByText('claude-test-1')).toBeInTheDocument()
    expect(panel.getByText('11/13, 09:00 Taipei')).toBeInTheDocument()
    expect(panel.getByText(/10\/16\/2026 to 11\/12\/2026\./)).toBeInTheDocument()
    expect(panel.getByText('+12.00%')).toHaveClass('text-up')
    expect(within(panel.getByRole('region', { name: 'What the company is' })).getByText(/It makes chips for other firms\./).textContent).toBe('It makes chips for other firms. Company listing · 11/13')
    const movement = within(panel.getByRole('region', { name: 'Why it rose or fell' }))
    expect(movement.getByText(/A report named new orders\./).textContent).toBe('A report named new orders. News · 11/11Board post · 11/9')
    expect(panel.getByText('For research and reference only, not investment advice.')).toBeInTheDocument()
    expect(panel.getByText('For research and reference only, not investment advice.')).toBeInTheDocument()
    expect(panel.queryByText(/This brief is in/)).not.toBeInTheDocument()
    expect(panel.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders the AI’s and a third party’s text as text, and links out only to an http address, else to the page’s own part', async () => {
    backend([answer({ today: written })])
    renderPanel()

    const panel = await screen.findByRole('region', { name: 'AI brief' })
    expect(await within(panel).findByText(/Revenue grew <b>fast<\/b>, see \[the report\]\(https:\/\/evil\.example\)\./)).toBeInTheDocument()
    expect(panel.querySelector('b, i')).toBeNull()
    const sources = within(within(panel).getByRole('region', { name: 'Cited sources' }))
    expect(sources.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Company listing · 11/13',
      'Monthly revenue · 11/10(shown on this page)',
      'News · 11/11Orders <i>rise</i>(opens the source in a new tab)',
      'Board post · 11/9(shown on this page)[標的] 2330',
    ])
    expect(within(panel).getAllByRole('link').map((link) => [link.getAttribute('href'), link.getAttribute('rel')])).toEqual([
      ['#stock-revenue', null],
      ['https://news.example/a', 'noopener noreferrer nofollow'],
      ['#stock-news-panel', null],
    ])
  })

  it('says which language the brief is in to a reader of another', async () => {
    backend([answer({ today: written })])
    renderPanel('zh-TW')

    expect(await screen.findByText('以英文寫成。')).toBeInTheDocument()
    expect(screen.getByText('月營收 · 11/10', { selector: 'span' })).toBeInTheDocument()
  })

  it('tells a visitor that signed-in users can ask, with no button, and never asks the AI by itself', async () => {
    const calls = backend([answer({})])
    renderPanel()

    expect(await screen.findByText('No brief has been written today')).toBeInTheDocument()
    expect(screen.getByText(/Signed-in users can ask for today’s brief\./)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(calls.post).toBe(0)
  })

  it('writes the brief once on a signed-in viewer’s click and shows it', async () => {
    let reply = (_response: Response) => {}
    const posting = new Promise<Response>((resolve) => (reply = resolve))
    const calls = backend([answer({ previous: earlier })], () => posting as unknown as Response)
    session.signIn(TEST_USER)
    const user = userEvent.setup()
    renderPanel()

    expect(await screen.findByText('Earlier brief, of 11/12/2026')).toBeInTheDocument()
    expect(screen.getByText('Uses one of your AI calls today.')).toBeInTheDocument()
    expect(calls.post).toBe(0)
    await user.click(screen.getByRole('button', { name: 'Write today’s brief' }))

    expect(await screen.findByText('Today’s brief is being written')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText(/Yesterday’s words\./)).toBeInTheDocument()
    reply(json(answer({ today: written, previous: earlier, stocks_left: 4 })))

    expect(await screen.findByText(/It makes chips for other firms\./)).toBeInTheDocument()
    expect(screen.queryByText(/Yesterday’s words\./)).not.toBeInTheDocument()
    expect(calls).toEqual({ get: 1, post: 1 })
  })

  it('says each step of a first brief and which one the site is at, from what the site holds as it is asked again', async () => {
    let reply = (_response: Response) => {}
    const posting = new Promise<Response>((resolve) => (reply = resolve))
    const company = { held: nothingHeld }
    backend([answer({})], () => posting as unknown as Response, company)
    session.signIn(TEST_USER)
    const user = userEvent.setup()
    renderPanel()
    const steps = () => screen.getAllByRole('listitem').map((step) => step.textContent)

    await user.click(await screen.findByRole('button', { name: 'Write today’s brief' }))

    await waitFor(() =>
      expect(steps()).toEqual([
        'Read the company’s main business on MOPS(in progress)',
        'Read its annual report(waiting)',
        'Write the company card(waiting)',
        'Write today’s brief(waiting)',
      ]),
    )

    const profile = { stock_id: '2330', main_business_fetched_at: '2026-11-13T01:00:05Z', annual_report_checked_at: '2026-11-13T01:00:25Z' }
    company.held = { ...nothingHeld, profile: profile as StockCompanyAnswer['profile'], today: today('writing') }

    await waitFor(() => expect(steps().map((step) => step?.match(/\((.+)\)/)?.[1])).toEqual(['done', 'done', 'in progress', 'waiting']), {
      timeout: BRIEF_POLL_MS + 2_000,
    })
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('Write the company card')

    reply(json(answer({ today: written })))
    expect(await screen.findByText(/It makes chips for other firms\./)).toBeInTheDocument()
    expect(screen.queryByText('Write the company card')).not.toBeInTheDocument()
  }, 15_000)

  it('shows the earlier brief while another viewer’s request is being written, and asks again until it is', async () => {
    const calls = backend([answer({ today: today('writing'), previous: earlier }), answer({ today: written, previous: earlier })])
    session.signIn(TEST_USER)
    renderPanel()

    expect(await screen.findByText('Today’s brief is being written')).toBeInTheDocument()
    expect(screen.getByText('Earlier brief, of 11/12/2026')).toBeInTheDocument()
    expect(screen.getByText(/Yesterday’s words\./)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()

    expect(await screen.findByText(/It makes chips for other firms\./, undefined, { timeout: BRIEF_POLL_MS + 2_000 })).toBeInTheDocument()
    expect(calls).toEqual({ get: 2, post: 0 })
    await new Promise((resolve) => setTimeout(resolve, BRIEF_POLL_MS + 500))
    expect(calls.get).toBe(2)
  }, 15_000)

  it('says a failed brief could not be written, shows the earlier one and lets a signed-in viewer try again', async () => {
    const calls = backend([answer({ today: today('failed'), previous: earlier, stocks_left: 0 })])
    session.signIn(TEST_USER)
    const user = userEvent.setup()
    renderPanel()

    expect(await screen.findByText('Today’s brief could not be written')).toBeInTheDocument()
    expect(screen.getByText('Earlier brief, of 11/12/2026')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText(/It makes chips for other firms\./)).toBeInTheDocument()
    expect(calls.post).toBe(1)
  })

  it('says the day’s limit of new briefs is reached, with no button', async () => {
    backend([answer({ stocks_left: 0 })])
    session.signIn(TEST_USER)
    renderPanel()

    expect(await screen.findByText('Today’s limit of new briefs is reached')).toBeInTheDocument()
    expect(screen.getByText('It resets at midnight in Taiwan.')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says the AI allowance is spent when the server refuses for it, and offers no second try', async () => {
    const calls = backend([answer({})], () => json({ detail: 'Today’s paid AI calls are spent.', code: 'ai_allowance_spent' }, 429))
    session.signIn(TEST_USER)
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Write today’s brief' }))

    expect(await screen.findByText('Today’s AI calls are used up, yours or the site’s. They renew at midnight Taiwan time.')).toBeInTheDocument()
    expect(screen.getByText('Today’s brief could not be written')).toBeInTheDocument()
    await waitFor(() => expect(calls.get).toBe(2))
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(calls.post).toBe(1)
  })

  it('says so when the brief cannot be loaded', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'down', code: 'request_refused' }, 500)))
    renderPanel()

    expect(await screen.findByText('The brief could not be loaded.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
