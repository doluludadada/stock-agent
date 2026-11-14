import { ApiError } from '@/shared/api'
import { briefSteps, briefView, sourceLink, type StockBrief, type StockBriefAnswer, type StockCompanyAnswer } from './brief'

const held: StockBriefAnswer = { stock_id: '2330', today: null, previous: null, stocks_left: 3 }
const refusal = (code: string) => new ApiError('rateLimited', 429, 'refused', [], null, { detail: 'refused', code })
const idle = { pending: false, error: null }

describe('what the brief’s card says', () => {
  it('reads a refusal for the day’s limit as the limit, and offers no retry after a spent AI allowance', () => {
    expect(briefView(held, { pending: false, error: refusal('brief_limit_reached') }, 'signedIn')).toEqual({ kind: 'limit', earlier: null })
    expect(briefView(held, { pending: false, error: refusal('ai_allowance_spent') }, 'signedIn')).toMatchObject({ kind: 'failed', ask: 'none' })
    expect(briefView(held, { pending: false, error: new Error('lost') }, 'signedIn')).toMatchObject({ kind: 'failed', ask: 'write' })
  })

  it('offers the write to a signed-in viewer, the sign-in to a visitor and nothing while the session is unknown', () => {
    expect((['signedIn', 'signedOut', 'checking'] as const).map((viewer) => briefView(held, idle, viewer))).toEqual([
      { kind: 'unwritten', ask: 'write', earlier: null },
      { kind: 'unwritten', ask: 'signIn', earlier: null },
      { kind: 'unwritten', ask: 'none', earlier: null },
    ])
  })

  it('leads a source to its own http address, else to the page’s part of its kind, else nowhere', () => {
    const source = { key: 'S1', dated: '2026-11-12', title: null }
    expect(sourceLink({ ...source, kind: 'news', url: 'https://news.example/a' })).toEqual({ to: 'outbound', href: 'https://news.example/a' })
    expect(sourceLink({ ...source, kind: 'news', url: 'javascript:alert(1)' })).toEqual({ to: 'section', anchor: 'stock-news-panel' })
    expect(sourceLink({ ...source, kind: 'company', url: null })).toEqual({ to: 'nowhere' })
  })
})

describe('how far a request for a brief has come', () => {
  const card = { status: 'written', company: [{ text: 'It makes chips.', sources: ['S1'] }] } as StockBrief
  const company = (parts: Partial<StockCompanyAnswer>): StockCompanyAnswer => ({ stock_id: '2330', profile: null, sources: [], today: null, previous: null, ...parts })
  const profile = (parts: object) => ({ stock_id: '2330', ...parts }) as StockCompanyAnswer['profile']
  const personal = { mainBusiness: true, annualReports: true }
  const states = (steps: ReturnType<typeof briefSteps>) => steps.map(({ step, state }) => `${step} ${state}`)

  it('works on the first thing the site does not hold yet, in the order the site does them', () => {
    expect(states(briefSteps(undefined, held, personal))).toEqual(['mainBusiness active', 'annualReport waiting', 'card waiting', 'brief waiting'])
    expect(states(briefSteps(company({ profile: profile({ main_business_fetched_at: '2026-11-13T01:00:00Z' }) }), held, personal))).toEqual([
      'mainBusiness done',
      'annualReport active',
      'card waiting',
      'brief waiting',
    ])
    const read = profile({ main_business_fetched_at: '2026-11-13T01:00:00Z', annual_report_checked_at: '2026-11-13T01:00:20Z' })
    expect(states(briefSteps(company({ profile: read }), held, personal)).slice(2)).toEqual(['card active', 'brief waiting'])
    expect(states(briefSteps(company({ profile: read, previous: card }), held, personal)).slice(2)).toEqual(['card done', 'brief active'])
  })

  it('believes a card or a brief that is being written, whatever the site holds of the steps before', () => {
    const writing = { ...card, status: 'writing' } as StockBrief
    expect(states(briefSteps(company({ today: writing, previous: card }), held, personal))).toEqual(['mainBusiness done', 'annualReport done', 'card active', 'brief waiting'])
    expect(states(briefSteps(company({}), { ...held, today: writing }, personal))).toEqual(['mainBusiness done', 'annualReport done', 'card done', 'brief active'])
  })

  it('names no reading of MOPS or of the annual report on a site that reads neither', () => {
    expect(states(briefSteps(company({}), held, { mainBusiness: false, annualReports: false }))).toEqual(['card active', 'brief waiting'])
  })
})
