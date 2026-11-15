import { isApiError, type Schemas, type Session } from '@/shared/api'
import { outboundUrl } from '@/shared/lib/outbound-url'

export type StockBriefAnswer = Schemas['StockBriefResponse']
export type StockBrief = Schemas['StockBrief']
export type BriefSentence = Schemas['BriefSentence']
export type BriefSource = Schemas['BriefSource']
export type StockCompanyAnswer = Schemas['StockCompanyResponse']
export type CompanyProfile = Schemas['CompanyProfile']

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

/** The company's card: the one claimed today once it is written, else the newest written one of an earlier day. */
export function companyCard(answer: StockCompanyAnswer): StockBrief | null {
  return answer.today?.status === 'written' ? answer.today : (answer.previous ?? null)
}

export interface CompanyLink {
  kind: 'profile' | 'annual_report'
  href: string
}

/**
 * The pages the company's facts are from, one per kind: MOPS's page of the company, and the document site's page that
 * lists its annual report, whose sections share it. Only a plain http or https address is a link.
 */
export function companyLinks(answer: StockCompanyAnswer): CompanyLink[] {
  const links: CompanyLink[] = []
  for (const kind of ['profile', 'annual_report'] as const) {
    const href = answer.sources.map((source) => (source.kind === kind ? outboundUrl(source.url?.split('#')[0] ?? null) : null)).find(Boolean)
    if (href) links.push({ kind, href })
  }
  return links
}

/** One thing the site does for a stock's brief, in the order it does them, and how far it has come. */
export interface BriefStep {
  step: 'mainBusiness' | 'annualReport' | 'card' | 'brief'
  state: 'done' | 'active' | 'waiting'
}

/**
 * How far a request for today's brief has come, from what the site holds now: the company's main business read from
 * MOPS and its annual report looked for, on a site that reads them (`reads`), then its card, then the brief. A step
 * is done once the site holds what it leaves, and the one being worked on is the first that is not; a card or a
 * brief being written says so itself, whatever came before it.
 */
export function briefSteps(
  company: StockCompanyAnswer | undefined,
  brief: StockBriefAnswer,
  reads: { mainBusiness: boolean; annualReports: boolean },
): BriefStep[] {
  const profile = company?.profile
  const cardWriting = company?.today?.status === 'writing'
  const steps: { step: BriefStep['step']; done: boolean }[] = [
    ...(reads.mainBusiness ? [{ step: 'mainBusiness' as const, done: Boolean(profile?.main_business_fetched_at) }] : []),
    ...(reads.annualReports ? [{ step: 'annualReport' as const, done: Boolean(profile?.annual_report_checked_at) }] : []),
    { step: 'card', done: !cardWriting && company !== undefined && companyCard(company) !== null },
    { step: 'brief', done: false },
  ]
  const card = steps.length - 2
  const active = brief.today?.status === 'writing' ? card + 1 : cardWriting ? card : steps.findIndex((step) => !step.done)
  return steps.map(({ step }, index) => ({ step, state: index < active ? 'done' : index === active ? 'active' : 'waiting' }))
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
  annual_report: null,
  profile: null,
  world_news: null,
  indicator: null,
} as const satisfies Record<BriefSource['kind'], string | null>

export type SourceLink = { to: 'outbound'; href: string } | { to: 'section'; anchor: string } | { to: 'nowhere' }

/** Where a cited source leads: its own address when that is plain http or https, else the page's part of its kind. */
export function sourceLink(source: BriefSource): SourceLink {
  const href = outboundUrl(source.url ?? null)
  if (href) return { to: 'outbound', href }
  const anchor = SECTION_ANCHORS[source.kind]
  return anchor ? { to: 'section', anchor } : { to: 'nowhere' }
}
