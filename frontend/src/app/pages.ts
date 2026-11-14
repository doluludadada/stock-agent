import type { Feature } from '@/shared/api'

const RUN_FEATURES = ['full_cycle', 'specific_stock', 'buzz', 'intraday'] as const

/**
 * Every page with the features it belongs to. The site shows a page to a viewer who sees any one of them, and a page
 * that names none always. The navigation and the routes both read this table, so a page never has an entry without
 * an address or the other way round.
 */
export const PAGE_FEATURES = {
  home: [],
  overview: ['market_overview'],
  ranking: ['ranking'],
  valuation: ['valuation'],
  stock: ['stock_pages'],
  watchlist: ['watchlist'],
  holdings: ['holdings'],
  account: ['mock_account'],
  brokerage: ['sinopac_account'],
  settings: [],
  runs: RUN_FEATURES,
  run: RUN_FEATURES,
  strategies: ['strategy_library'],
  backtest: ['strategy_backtest'],
  builder: ['strategy_designer'],
  users: [],
  admin: [],
  attribution: [],
} as const satisfies Record<string, readonly Feature[]>

export type Page = keyof typeof PAGE_FEATURES

/**
 * Features that open no page. Ordering on SinoPac acts inside pages other features open, and the server's answers
 * carry it: `/v1/account/brokers` offers SinoPac to a run only while it shows, and the SinoPac account page says its
 * state from `ordering`. Naming it at a page would open that page to a viewer who sees ordering alone.
 */
export const FEATURES_WITHOUT_PAGE = ['sinopac_ordering'] as const satisfies readonly Feature[]
