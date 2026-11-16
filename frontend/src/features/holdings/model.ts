import type { DailyBar, Schemas } from '@/shared/api'
import { sessionDate } from '@/shared/lib/chart-range'
import { dayMove, type DayMove } from '@/shared/lib/day-move'

export type Holdings = Schemas['HoldingsResponse']
export type Holding = Schemas['HoldingResponse']
export type HoldingSource = Schemas['HoldingSource']
export type HoldingEntry = Schemas['HoldingRequest']

/** The API's bounds of a hand-entered holding (`HoldingRequest` in openapi.json); model.test.ts compares them. */
export const QUANTITY_MAX = 1_000_000_000
export const AVERAGE_COST_MAX = 1_000_000

/** The order the sources read in everywhere: what is really held first, the mock account's play money last. */
export const SOURCE_ORDER = ['brokerage', 'manual', 'mock'] as const satisfies readonly HoldingSource[]

/** A stock held at the broker and entered by hand is two holdings, so a row is named by its source and its stock. */
export const holdingKey = (holding: Holding) => `${holding.source}:${holding.position.stock_id}`

const inOrder = (sources: readonly HoldingSource[]) => SOURCE_ORDER.filter((source) => sources.includes(source))

/** The sources the site shows this user, from the `asked` of an answer asked with no filter. */
export const offeredSources = (asked: readonly HoldingSource[]): HoldingSource[] => inOrder(asked)

/**
 * The `sources` to send for a choice: null asks with no filter, which is every offered source and is what the page
 * asked first, so choosing them all again asks nothing new.
 */
export function sourcesToAsk(offered: readonly HoldingSource[], chosen: readonly HoldingSource[] | null): HoldingSource[] | null {
  if (chosen === null) return null
  const kept = inOrder(chosen.filter((source) => offered.includes(source)))
  return kept.length === 0 || kept.length === offered.length ? null : kept
}

/** The choice after one source's box changes. The last one stays checked: a portfolio of no source says nothing. */
export function toggledSources(offered: readonly HoldingSource[], chosen: readonly HoldingSource[] | null, source: HoldingSource): HoldingSource[] {
  const current = chosen ?? offered
  const next = current.includes(source) ? current.filter((item) => item !== source) : [...current, source]
  return inOrder(next.length === 0 ? current : next)
}

/** The sources asked that could not be read now; the brokerage is one while the site's SinoPac login is down. */
export function unreadSources(holdings: Pick<Holdings, 'asked' | 'sources'>): HoldingSource[] {
  return inOrder(holdings.asked.filter((source) => !holdings.sources.includes(source)))
}

export interface WatchedStock {
  stockId: string
  name: string | null
}

/** The watched stocks with no hand-entered holding: a watchlist entry and a holding stay different things. */
export function watchedWithoutEntry(watched: readonly WatchedStock[], holdings: readonly Holding[]): WatchedStock[] {
  const entered = new Set(holdings.filter((holding) => holding.source === 'manual').map((holding) => holding.position.stock_id))
  return watched.filter((stock) => !entered.has(stock.stockId))
}

/** The entry form as typed. The stock is chosen from the listing, never typed. */
export interface EntryDraft {
  stockId: string | null
  quantity: string
  averageCost: string
  /** YYYY-MM-DD, or empty when the day bought is not known. */
  openedOn: string
}

export const EMPTY_DRAFT: EntryDraft = { stockId: null, quantity: '', averageCost: '', openedOn: '' }

export type EntryField = keyof EntryDraft

export type ParsedEntry = { entry: HoldingEntry; problems: null } | { entry: null; problems: EntryField[] }

/** The request for a draft, or the fields the API would refuse: whole shares from 1, a cost above 0, a day up to `today`. */
export function parseEntry(draft: EntryDraft, today: string): ParsedEntry {
  const quantity = /^\d+$/.test(draft.quantity.trim()) ? Number(draft.quantity) : Number.NaN
  const averageCost = draft.averageCost.trim() === '' ? Number.NaN : Number(draft.averageCost)
  const day = draft.openedOn.trim()
  const problems: EntryField[] = [
    ...(draft.stockId === null ? (['stockId'] as const) : []),
    ...(quantity >= 1 && quantity <= QUANTITY_MAX ? [] : (['quantity'] as const)),
    ...(averageCost > 0 && averageCost <= AVERAGE_COST_MAX ? [] : (['averageCost'] as const)),
    ...(day === '' || (/^\d{4}-\d{2}-\d{2}$/.test(day) && day <= today) ? [] : (['openedOn'] as const)),
  ]
  if (draft.stockId === null || problems.length > 0) return { entry: null, problems }
  return { entry: { confirm: true, stock_id: draft.stockId, quantity, average_cost: averageCost, ...(day ? { opened_on: day } : {}) }, problems: null }
}

/** A hand-entered holding as the form shows it for a change; its day is the Taipei day it was opened. */
export function draftOf({ position }: Holding): EntryDraft {
  return {
    stockId: position.stock_id,
    quantity: String(position.quantity),
    averageCost: String(position.average_cost),
    openedOn: position.opened_at ? sessionDate(position.opened_at) : '',
  }
}

/** What the server valued at today's quotes in a portfolio. */
export interface QuotedHoldings {
  /** The rows valued at a quote, by holdingKey. */
  quoted: ReadonlySet<string>
  /** Today's move of those rows, from the exchange's change each quote carries; null when none is valued at a quote. */
  day: DayMove | null
  /** The latest trade among the quotes the server used. */
  tradedAt: string | null
}

/**
 * Which holdings the server valued at today's quote (`live_stock_ids`), when the newest of those quotes was traded,
 * and today's move of them. Every figure of the portfolio stays the server's: the worth, the gain or loss, the
 * weights, the concentration and the ranking's shares are all computed there, at those quotes.
 */
export function quotedHoldings(holdings: Holdings, quotes: ReadonlyMap<string, DailyBar>): QuotedHoldings {
  const live = new Set(holdings.live_stock_ids)
  const rows = holdings.holdings.filter((row) => live.has(row.position.stock_id))
  return {
    quoted: new Set(rows.map(holdingKey)),
    day: dayMove(rows.map((row) => ({ quantity: row.position.quantity, quoted: quotes.get(row.position.stock_id) }))),
    tradedAt: rows.flatMap((row) => row.position.marked_at ?? []).sort().at(-1) ?? null,
  }
}
