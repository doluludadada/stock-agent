/**
 * Stock ids as the API takes them: letters and digits, at most 10, and lists of at most 20 distinct ids. These are
 * the contract's `stock_id` pattern and `StockIdList`; stock-ids.test.ts compares both with openapi.json.
 */
export const STOCK_ID = /^[0-9A-Za-z]{1,10}$/
export const MAX_STOCK_IDS = 20

export function isStockId(text: string): boolean {
  return STOCK_ID.test(text)
}

export interface StockIdList {
  /** Distinct ids in the order typed, upper-cased like the exchange lists them. */
  ids: string[]
  /** Typed tokens that are not stock ids. */
  invalid: string[]
}

/** Splits typed text on spaces, commas (half or full width) and the ideographic comma; a repeated id counts once. */
export function parseStockIds(text: string): StockIdList {
  const tokens = [...new Set(text.split(/[\s,，、]+/).filter(Boolean).map((token) => token.toUpperCase()))]
  return { ids: tokens.filter(isStockId), invalid: tokens.filter((token) => !isStockId(token)) }
}

/** A list the API accepts: at least one id, no invalid token and at most MAX_STOCK_IDS ids. */
export function isAcceptedList(list: StockIdList): boolean {
  return list.ids.length > 0 && list.invalid.length === 0 && list.ids.length <= MAX_STOCK_IDS
}
