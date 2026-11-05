import openapi from '@/shared/api/openapi.json'
import { isAcceptedList, isStockId, MAX_STOCK_IDS, parseStockIds, STOCK_ID } from './stock-ids'

type Schema = { pattern?: string; maxItems?: number; minItems?: number }
const paths = openapi.paths as unknown as Record<string, Record<string, { parameters?: { name: string; schema: Schema }[] }>>
const schemas = openapi.components.schemas as unknown as Record<string, Schema>

describe('stock ids follow the API contract', () => {
  it('uses the pattern of the stock id path parameter', () => {
    const parameter = paths['/v1/market/stocks/{stock_id}']!.get!.parameters!.find((item) => item.name === 'stock_id')!
    expect(STOCK_ID.source).toBe(parameter.schema.pattern)
  })

  it('caps a list where the API caps it', () => {
    expect(MAX_STOCK_IDS).toBe(schemas.StockIdList!.maxItems)
    const valuation = paths['/v1/valuation/stocks']!.get!.parameters!.find((item) => item.name === 'stock_ids')!
    expect(MAX_STOCK_IDS).toBe(valuation.schema.maxItems)
  })
})

describe('parseStockIds', () => {
  it('splits on spaces, half and full width commas and the ideographic comma, and keeps the typed order', () => {
    expect(parseStockIds(' 2330, 2317，0050、2454\n6505 ').ids).toEqual(['2330', '2317', '0050', '2454', '6505'])
  })

  it('counts a repeated id once, whatever its case', () => {
    expect(parseStockIds('00632r 00632R 2330 2330').ids).toEqual(['00632R', '2330'])
  })

  it('names the tokens that are not stock ids instead of dropping them', () => {
    const list = parseStockIds('2330 23-30 12345678901')
    expect(list.ids).toEqual(['2330'])
    expect(list.invalid).toEqual(['23-30', '12345678901'])
    expect(isAcceptedList(list)).toBe(false)
  })

  it('accepts up to the cap and refuses one more', () => {
    const ids = Array.from({ length: MAX_STOCK_IDS + 1 }, (_, index) => String(1000 + index))
    expect(isAcceptedList(parseStockIds(ids.slice(0, MAX_STOCK_IDS).join(' ')))).toBe(true)
    expect(isAcceptedList(parseStockIds(ids.join(' ')))).toBe(false)
  })

  it('refuses an empty list', () => {
    expect(isAcceptedList(parseStockIds('  ,、 '))).toBe(false)
  })
})

describe('isStockId', () => {
  it('takes letters and digits up to ten characters', () => {
    expect(isStockId('2330')).toBe(true)
    expect(isStockId('00632R')).toBe(true)
    expect(isStockId('')).toBe(false)
    expect(isStockId('2330 ')).toBe(false)
    expect(isStockId('../admin')).toBe(false)
  })
})
