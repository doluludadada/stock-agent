import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n, type Locale } from '@/i18n'
import { session } from '@/shared/api'
import { companyCard, companyLinks, type CompanyProfile, type StockBrief, type StockCompanyAnswer } from './brief'
import { CompanyPanel } from './CompanyPanel'

const MOPS = 'https://mops.example/t05st03?co_id=5209'
const INDEX = 'https://doc.example/t57sb01?co_id=5209&year=115'

const profile: CompanyProfile = {
  stock_id: '5209',
  market: 'tpex',
  full_name: '新鼎系統股份有限公司',
  short_name: '新鼎',
  english_short_name: 'CTCI ASI',
  industry_code: '20',
  founded_on: '1987-08-03',
  listed_on: '2002-02-25',
  paid_in_capital: 285_672_240,
  issued_shares: 28_567_224,
  chairman: '鍾士偉',
  general_manager: '謝仁興',
  address: null,
  website: 'http://www.asi.ctci.com',
  reported_on: '2026-11-14',
  fetched_at: '2026-11-14T12:00:00Z',
  main_business: 'Control systems <b>integration</b>',
  english_name: 'CTCI Advanced Systems Inc.',
  main_business_url: MOPS,
  main_business_fetched_at: '2026-11-14T12:00:00Z',
  annual_report_year: 2025,
  annual_report_file: '2025_5209_20260526F04.pdf',
  annual_report_checked_at: '2026-11-14T12:00:00Z',
}

const sources: StockCompanyAnswer['sources'] = [
  { key: 'S1', kind: 'company', dated: '2026-11-14', title: null, url: null },
  { key: 'S2', kind: 'profile', dated: '2026-11-14', title: null, url: MOPS },
  { key: 'S3', kind: 'annual_report', dated: '2026-05-07', title: '114年度股東會年報：業務範圍', url: `${INDEX}#business_scope` },
  { key: 'S4', kind: 'annual_report', dated: '2026-05-07', title: '114年度股東會年報：主要產品及營業比重', url: `${INDEX}#product_mix` },
]

const card: StockBrief = {
  stock_id: '5209',
  day: '2026-11-14',
  status: 'written',
  language: 'en',
  model: 'claude-test-1',
  claimed_at: '2026-11-14T01:00:00Z',
  written_at: '2026-11-14T01:00:20Z',
  window_first: null,
  window_last: null,
  price_change: null,
  company: [
    { text: 'It integrates control systems for plants.', sources: ['S2', 'S3'] },
    { text: 'Construction was 80.65% of 2025 revenue, see [more](https://evil.example).', sources: ['S4'] },
  ],
  movement: [],
  sources,
  fingerprint: 'a'.repeat(64),
}

const held = (parts: Partial<StockCompanyAnswer> = {}): StockCompanyAnswer => ({ stock_id: '5209', profile, sources, today: null, previous: card, ...parts })
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function backend(answer: () => Response) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    expect(url).toBe('/v1/market/stocks/5209/company')
    expect(init?.method ?? 'GET').toBe('GET')
    return answer()
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function renderPanel(locale: Locale = 'en') {
  const i18n = initI18n('en')
  void i18n.changeLanguage(locale)
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <CompanyPanel stockId="5209" />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('a stock’s company card', () => {
  beforeEach(() => session.signOut())
  afterEach(() => vi.unstubAllGlobals())

  it('shows a visitor the card with its AI label, the facts and the two source pages, and asks the server once', async () => {
    const fetch = backend(() => json(held()))
    renderPanel()

    const panel = within(await screen.findByRole('region', { name: 'Company' }))
    expect((await panel.findByText(/It integrates control systems for plants\./)).textContent).toBe(
      'It integrates control systems for plants. MOPS company profile · 11/14Annual report · 5/7',
    )
    expect(panel.getByText('AI-generated, may be wrong')).toBeInTheDocument()
    expect(panel.getByText('claude-test-1')).toBeInTheDocument()
    expect(panel.getByText('Founded').nextSibling?.textContent).toBe('08/03/1987')
    expect(panel.getByText('Listed').nextSibling?.textContent).toBe('02/25/2002')
    expect(panel.getByText('Paid-in capital').nextSibling?.textContent).toBe('NT$285.7M')
    expect(panel.getByText('Chairman').nextSibling?.textContent).toBe('鍾士偉')
    expect(panel.getByRole('link', { name: /www\.asi\.ctci\.com/ })).toHaveAttribute('href', 'http://www.asi.ctci.com/')
    expect(panel.getByRole('link', { name: /MOPS company profile/ })).toHaveAttribute('href', MOPS)
    expect(panel.getByRole('link', { name: /Annual report/ })).toHaveAttribute('href', INDEX)
    expect(panel.getAllByRole('link')).toHaveLength(3)
    expect(panel.queryByRole('button')).not.toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('renders the AI’s and the company’s text as text', async () => {
    backend(() => json(held()))
    renderPanel()

    const panel = await screen.findByRole('region', { name: 'Company' })
    expect(await within(panel).findByText(/see \[more\]\(https:\/\/evil\.example\)\./)).toBeInTheDocument()
    expect(within(panel).queryByText(/Main business:/)).not.toBeInTheDocument()
    expect(panel.querySelector('b, i')).toBeNull()
  })

  it('shows the main business as the company filed it only while there is no card, as text', async () => {
    backend(() => json(held({ previous: null })))
    renderPanel()

    const panel = await screen.findByRole('region', { name: 'Company' })
    expect(await within(panel).findByText(/Control systems <b>integration<\/b>/)).toBeInTheDocument()
    expect(within(panel).getByText('Main business:')).toBeInTheDocument()
    expect(panel.querySelector('b, i')).toBeNull()
  })

  it('shows the facts alone while no card is written, and a card being written or failed today keeps the earlier one', async () => {
    backend(() => json(held({ previous: null, today: { ...card, status: 'failed', company: [], written_at: null } })))
    renderPanel('zh-TW')

    const panel = within(await screen.findByRole('region', { name: '公司' }))
    expect(await panel.findByText('董事長')).toBeInTheDocument()
    expect(panel.getByText('實收資本額').nextSibling?.textContent).toBe('2.9億 元')
    expect(panel.getByText(/主要業務：/)).toBeInTheDocument()
    expect(panel.queryByText('AI 生成，可能有錯')).not.toBeInTheDocument()
    expect(companyCard(held({ today: { ...card, status: 'writing' } }))).toBe(card)
    expect(companyCard(held({ today: { ...card, day: '2026-11-15' } }))?.day).toBe('2026-11-15')
  })

  it('leaves out a fact the site does not hold and links no address that is not plain http', async () => {
    const bare: CompanyProfile = { ...profile, founded_on: null, chairman: null, website: 'javascript:alert(1)', main_business: null }
    const unsafe = sources.map((source) => (source.kind === 'profile' ? { ...source, url: 'javascript:alert(1)' } : source))
    backend(() => json(held({ profile: bare, sources: unsafe, previous: null })))
    renderPanel()

    const panel = within(await screen.findByRole('region', { name: 'Company' }))
    expect(await panel.findByText('Listed')).toBeInTheDocument()
    expect(panel.queryByText('Founded')).not.toBeInTheDocument()
    expect(panel.queryByText('Chairman')).not.toBeInTheDocument()
    expect(panel.queryByText('Website')).not.toBeInTheDocument()
    expect(panel.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual([INDEX])
    expect(companyLinks(held({ sources: [] }))).toEqual([])
  })

  it('says so when the site holds nothing about the company', async () => {
    backend(() => json(held({ profile: null, sources: sources.slice(0, 1), previous: null })))
    renderPanel()
    expect(await screen.findByText('No company facts held yet')).toBeInTheDocument()
  })

  it('shows a failed load with a way to try again', async () => {
    backend(() => json({ detail: 'down', code: 'unavailable' }, 503))
    renderPanel()

    expect(await screen.findByText('The company’s facts could not be loaded.')).toBeInTheDocument()
    expect(screen.getByRole('button')).toBeInTheDocument()
  })
})
