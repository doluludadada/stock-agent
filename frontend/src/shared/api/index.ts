export { ApiError, apiRequest, isApiError, type ApiErrorKind, type ErrorCode, type FieldProblem } from './http'
export { hasPermission, session, useHasPermission, useIsSignedIn, useSession, type Permission, type Session, type User } from './session'
export { runResultsKey, strategyResultsKey } from './query-keys'
export { allows, useAllows, useAudience, type Audience, type Capability } from './audience'
export {
  marketKeys,
  useArchiveStatus,
  useIndexHistory,
  useListedNames,
  useMarketBreadth,
  useMostTraded,
  useStockHistory,
  useStockQuotes,
  useStockSearch,
  type ArchiveStatus,
  type DailyBar,
  type IndexHistory,
  type ListedStock,
  type Loadable,
  type MarketBreadth,
  type MarketIndex,
  type SearchState,
  type StockHistory,
  type StockQuote,
} from './market'
export type { components } from './schema.gen'

import type { components } from './schema.gen'

export type Schemas = components['schemas']
