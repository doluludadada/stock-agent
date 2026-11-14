import { ApiError } from '@/shared/api'
import { briefView, sourceLink, type StockBriefAnswer } from './brief'

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
