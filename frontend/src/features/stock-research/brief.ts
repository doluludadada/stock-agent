import { isApiError, type Schemas, type Session } from '@/shared/api'
import { outboundUrl } from './model'

export type StockBriefAnswer = Schemas['StockBriefResponse']
export type StockBrief = Schemas['StockBrief']
export type BriefSentence = Schemas['BriefSentence']
export type BriefSource = Schemas['BriefSource']

/** What the viewer may do about a brief that is not written: ask for it, sign in to ask, or nothing. */
export type BriefAsk = 'write' | 'signIn' | 'none'

/**
 * The one thing the brief's card says. `earlier` is the newest written brief of a day before, shown under every state
 * but a written one. A failed brief carries the refused request, or null where the server holds today's as failed.
 */
export type BriefView =
  | { kind: 'written'; brief: StockBrief }
  | { kind: 'writing'; earlier: StockBrief | null }
  | { kind: 'failed'; error: unknown; ask: BriefAsk; earlier: StockBrief | null }
  | { kind: 'limit'; earlier: StockBrief | null }
  | { kind: 'unwritten'; ask: BriefAsk; earlier: StockBrief | null }

/** The viewer's own request for today's brief, as the page holds it. */
export interface BriefAttempt {
  pending: boolean
  error: unknown
}

const refusedAs = (error: unknown, code: 'brief_limit_reached' | 'ai_allowance_spent') => isApiError(error) && error.code === code

/**
 * What the server holds decides first: a written brief shows, a claimed one is being written. Then the viewer's own
 * refused request, then a failed brief, which may be asked again whatever is left of the day's new briefs.
 */
export function briefView(answer: StockBriefAnswer, attempt: BriefAttempt, viewer: Session['status']): BriefView {
  const { today, previous: earlier } = answer
  if (today?.status === 'written') return { kind: 'written', brief: today }
  if (attempt.pending || today?.status === 'writing') return { kind: 'writing', earlier }
  const ask: BriefAsk = viewer === 'signedIn' ? 'write' : viewer === 'signedOut' ? 'signIn' : 'none'
  if (attempt.error) {
    if (refusedAs(attempt.error, 'brief_limit_reached')) return { kind: 'limit', earlier }
    return { kind: 'failed', error: attempt.error, ask: refusedAs(attempt.error, 'ai_allowance_spent') ? 'none' : ask, earlier }
  }
  if (today?.status === 'failed') return { kind: 'failed', error: null, ask, earlier }
  if (answer.stocks_left <= 0) return { kind: 'limit', earlier }
  return { kind: 'unwritten', ask, earlier }
}

/** The held items a sentence rests on, in the order it cites them; a key the brief holds no source for is left out. */
export function citedSources(sentence: BriefSentence, sources: readonly BriefSource[]): BriefSource[] {
  return sentence.sources.flatMap((key) => sources.find((source) => source.key === key) ?? [])
}

/** The brief's sources a sentence cites, in the brief's own order. */
export function usedSources(brief: StockBrief): BriefSource[] {
  const cited = new Set([...(brief.company ?? []), ...(brief.movement ?? [])].flatMap((sentence) => sentence.sources))
  return (brief.sources ?? []).filter((source) => cited.has(source.key))
}

/** The part of the stock page that shows each kind of held item, by its element id; null where the page has none. */
export const SECTION_ANCHORS = {
  company: null,
  price: 'stock-price',
  revenue: 'stock-revenue',
  earnings: 'stock-financials',
  ranking: 'stock-score',
  announcement: 'stock-news-panel',
  exchange_news: 'stock-news-panel',
  news: 'stock-news-panel',
  post: 'stock-news-panel',
} as const satisfies Record<BriefSource['kind'], string | null>

export type SourceLink = { to: 'outbound'; href: string } | { to: 'section'; anchor: string } | { to: 'nowhere' }

/** Where a cited source leads: its own address when that is plain http or https, else the page's part of its kind. */
export function sourceLink(source: BriefSource): SourceLink {
  const href = outboundUrl(source.url ?? null)
  if (href) return { to: 'outbound', href }
  const anchor = SECTION_ANCHORS[source.kind]
  return anchor ? { to: 'section', anchor } : { to: 'nowhere' }
}
