import openapi from '@/shared/api/openapi.json'
import {
  AVERAGE_COST_MAX,
  draftOf,
  EMPTY_DRAFT,
  holdingKey,
  offeredSources,
  parseEntry,
  QUANTITY_MAX,
  SOURCE_ORDER,
  sourcesToAsk,
  toggledSources,
  unreadSources,
  watchedWithoutEntry,
  type EntryDraft,
  type Holding,
} from './model'

const TODAY = '2026-11-14'
const draft = (change: Partial<EntryDraft> = {}): EntryDraft => ({ stockId: '2330', quantity: '1000', averageCost: '512.5', openedOn: '', ...change })

function holding(source: Holding['source'], stockId: string, openedAt: string | null = null): Holding {
  return {
    source,
    stock_name: null,
    position: { stock_id: stockId, quantity: 250, average_cost: 98.7, mark_price: 100, marked_at: null, market_value: 25_000, unrealized_pnl: 0, cost_basis: 24_675, unrealized_return: 0, opened_at: openedAt },
    weight: 1,
    standing: null,
    revenue: null,
    accelerating_months: null,
  }
}

describe('a hand-entered holding follows the API contract', () => {
  const request = openapi.components.schemas.HoldingRequest.properties

  it('uses the bounds of the request', () => {
    expect(QUANTITY_MAX).toBe(request.quantity.maximum)
    expect(request.quantity.exclusiveMinimum).toBe(0)
    expect(request.quantity.type).toBe('integer')
    expect(AVERAGE_COST_MAX).toBe(request.average_cost.maximum)
    expect(request.average_cost.exclusiveMinimum).toBe(0)
  })

  it('names every source of the contract once, the play money last', () => {
    expect([...SOURCE_ORDER].sort()).toEqual([...openapi.components.schemas.HoldingSource.enum].sort())
    expect(SOURCE_ORDER.at(-1)).toBe('mock')
  })
})

describe('parseEntry', () => {
  it('makes the request of a valid draft, with the day only when one is given', () => {
    expect(parseEntry(draft(), TODAY)).toEqual({ entry: { confirm: true, stock_id: '2330', quantity: 1000, average_cost: 512.5 }, problems: null })
    expect(parseEntry(draft({ openedOn: TODAY }), TODAY).entry).toEqual({ confirm: true, stock_id: '2330', quantity: 1000, average_cost: 512.5, opened_on: TODAY })
  })

  it('takes an odd lot as its own count of shares, and the bounds themselves', () => {
    expect(parseEntry(draft({ quantity: '37' }), TODAY).entry?.quantity).toBe(37)
    expect(parseEntry(draft({ quantity: String(QUANTITY_MAX), averageCost: String(AVERAGE_COST_MAX) }), TODAY).problems).toBeNull()
  })

  it.each(['', '0', '-5', '1.5', '1,000', 'ten', String(QUANTITY_MAX + 1)])('refuses %j as shares', (quantity) => {
    expect(parseEntry(draft({ quantity }), TODAY)).toEqual({ entry: null, problems: ['quantity'] })
  })

  it.each(['', '0', '-1', 'abc', String(AVERAGE_COST_MAX + 1)])('refuses %j as an average cost', (averageCost) => {
    expect(parseEntry(draft({ averageCost }), TODAY)).toEqual({ entry: null, problems: ['averageCost'] })
  })

  it('refuses a day after today and a text that is no day', () => {
    expect(parseEntry(draft({ openedOn: '2026-11-15' }), TODAY).problems).toEqual(['openedOn'])
    expect(parseEntry(draft({ openedOn: '14/11/2026' }), TODAY).problems).toEqual(['openedOn'])
  })

  it('names every field of an empty form, the stock first', () => {
    expect(parseEntry(EMPTY_DRAFT, TODAY)).toEqual({ entry: null, problems: ['stockId', 'quantity', 'averageCost'] })
  })
})

describe('the sources of the portfolio', () => {
  it('reads the offered sources in one order whatever order the server lists them in', () => {
    expect(offeredSources(['manual', 'mock', 'brokerage'])).toEqual(['brokerage', 'manual', 'mock'])
    expect(offeredSources(['mock', 'manual'])).toEqual(['manual', 'mock'])
  })

  it('asks with no filter until a source is left out, and again once all are back', () => {
    const offered = offeredSources(['brokerage', 'manual', 'mock'])
    expect(sourcesToAsk(offered, null)).toBeNull()
    expect(sourcesToAsk(offered, ['mock', 'manual', 'brokerage'])).toBeNull()
    expect(sourcesToAsk(offered, ['manual', 'brokerage'])).toEqual(['brokerage', 'manual'])
  })

  it('never asks for a source the site does not offer the user', () => {
    expect(sourcesToAsk(['manual', 'mock'], ['brokerage', 'manual'])).toEqual(['manual'])
    expect(sourcesToAsk(['manual', 'mock'], ['brokerage'])).toBeNull()
  })

  it('checks and unchecks one source, and keeps the last one checked', () => {
    const offered = offeredSources(['brokerage', 'manual', 'mock'])
    expect(toggledSources(offered, null, 'mock')).toEqual(['brokerage', 'manual'])
    expect(toggledSources(offered, ['brokerage', 'manual'], 'mock')).toEqual(['brokerage', 'manual', 'mock'])
    expect(toggledSources(offered, ['manual'], 'manual')).toEqual(['manual'])
  })

  it('names a source that was asked and not read', () => {
    expect(unreadSources({ asked: ['brokerage', 'manual', 'mock'], sources: ['manual', 'mock'] })).toEqual(['brokerage'])
    expect(unreadSources({ asked: ['manual'], sources: ['manual'] })).toEqual([])
  })
})

describe('holdings and what is entered by hand', () => {
  it('keeps the same stock from two sources as two rows', () => {
    expect(holdingKey(holding('brokerage', '2330'))).not.toBe(holdingKey(holding('manual', '2330')))
  })

  it('offers a watched stock until it is entered by hand, whatever an account holds', () => {
    const watched = [
      { stockId: '2330', name: '台積電' },
      { stockId: '2317', name: '鴻海' },
    ]
    expect(watchedWithoutEntry(watched, [holding('brokerage', '2330'), holding('manual', '2317')])).toEqual([{ stockId: '2330', name: '台積電' }])
  })

  it('opens a change on the entry as it is held, its day in Taipei', () => {
    expect(draftOf(holding('manual', '00878', '2026-03-01T16:30:00Z'))).toEqual({ stockId: '00878', quantity: '250', averageCost: '98.7', openedOn: '2026-03-02' })
    expect(draftOf(holding('manual', '00878')).openedOn).toBe('')
  })
})
