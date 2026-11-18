import { Activity, Briefcase, Calculator, CandlestickChart, Globe, History, Home, Landmark, Layers, ListOrdered, Settings2, SlidersHorizontal, Sparkles, Star, UsersRound, Wallet, type LucideIcon } from 'lucide-react'
import type { ComponentType } from 'react'
import type { Capability, Feature, Permission } from '@/shared/api'
import { paths, patterns } from '@/shared/config/paths'

/** The navigation's sections in reading order; a folded one shows only its name until the reader opens it. */
export const SECTIONS = ['today', 'research', 'mine', 'tools', 'admin'] as const
export type SectionKey = (typeof SECTIONS)[number]
export const FOLDED_SECTIONS: readonly SectionKey[] = ['tools']

export interface PageEntry {
  path: string
  /** The site shows the page to a viewer who sees any one of these, and a page that names none always. */
  features: readonly Feature[]
  load: () => Promise<ComponentType>
  /** The page's entries show only to a user with this permission. The page itself says who it is for. */
  needs?: Permission
  /** The page's entries show only on a site whose audience allows this. */
  requires?: Capability
  /** Where the navigation lists the page: its section, and whether the phone's tab bar and the account menu list it too. */
  nav?: { section: SectionKey; icon: LucideIcon; tab?: true; menu?: true }
  /** The listed page that stays marked while this one is open. */
  under?: string
}

const RUN_FEATURES = ['full_cycle', 'specific_stock', 'buzz', 'intraday'] as const

/**
 * Every page, once: the router, the sidebar, the phone's tab bar, the account menu, the search palette and the feature
 * gate all read this table, so a new page is one entry. The order is the navigation's. A listed page's name is
 * `common:nav.<key>`.
 */
export const PAGES = {
  home: { path: paths.home, features: [], load: () => import('./router/routes/home').then((m) => m.HomeRoute), nav: { section: 'today', icon: Home, tab: true } },
  ranking: { path: paths.ranking, features: ['ranking'], load: () => import('./router/routes/ranking').then((m) => m.RankingRoute), nav: { section: 'research', icon: ListOrdered, tab: true } },
  overview: { path: paths.market, features: ['market_overview'], load: () => import('@/features/market-overview').then((m) => m.MarketOverviewPage), nav: { section: 'research', icon: CandlestickChart } },
  world: { path: paths.world, features: ['world'], load: () => import('@/features/world').then((m) => m.WorldPage), nav: { section: 'research', icon: Globe } },
  holdings: { path: paths.holdings, features: ['holdings'], load: () => import('./router/routes/holdings').then((m) => m.HoldingsRoute), nav: { section: 'mine', icon: Briefcase, tab: true } },
  watchlist: { path: paths.watchlist, features: ['watchlist'], load: () => import('@/features/watchlist').then((m) => m.WatchlistPage), nav: { section: 'mine', icon: Star } },
  brokerage: {
    path: paths.brokerage,
    features: ['sinopac_account'],
    load: () => import('./router/routes/brokerage').then((m) => m.BrokerageRoute),
    needs: 'use_real_broker',
    nav: { section: 'mine', icon: Landmark },
  },
  settings: { path: paths.mySettings, features: [], load: () => import('./router/routes/settings').then((m) => m.MySettingsRoute), nav: { section: 'mine', icon: SlidersHorizontal, menu: true } },
  runs: { path: paths.runs, features: RUN_FEATURES, load: () => import('./router/routes/runs').then((m) => m.RunsRoute), nav: { section: 'tools', icon: Activity } },
  account: { path: paths.account, features: ['mock_account'], load: () => import('@/features/account').then((m) => m.AccountPage), nav: { section: 'tools', icon: Wallet } },
  valuation: {
    path: paths.valuation,
    features: ['valuation'],
    load: () => import('./router/routes/valuation').then((m) => m.ValuationRoute),
    requires: 'mops',
    nav: { section: 'tools', icon: Calculator },
  },
  strategies: { path: paths.strategies, features: ['strategy_library'], load: () => import('./router/routes/strategies').then((m) => m.StrategyLibraryRoute), nav: { section: 'tools', icon: Layers } },
  backtest: { path: paths.backtest, features: ['strategy_backtest'], load: () => import('@/features/backtest').then((m) => m.BacktestPage), nav: { section: 'tools', icon: History } },
  builder: { path: paths.newStrategy, features: ['strategy_designer'], load: () => import('./router/routes/strategies').then((m) => m.NewStrategyRoute), nav: { section: 'tools', icon: Sparkles } },
  users: { path: paths.users, features: [], load: () => import('@/features/auth').then((m) => m.UsersPage), needs: 'manage_users', nav: { section: 'admin', icon: UsersRound, menu: true } },
  admin: {
    path: paths.adminSettings,
    features: [],
    load: () => import('@/features/admin-settings').then((m) => m.AdminSettingsPage),
    needs: 'edit_system_settings',
    nav: { section: 'admin', icon: Settings2, menu: true },
  },
  run: { path: patterns.run, features: RUN_FEATURES, load: () => import('./router/routes/runs').then((m) => m.RunRoute), under: 'runs' },
  editStrategy: { path: patterns.editStrategy, features: ['strategy_designer'], load: () => import('./router/routes/strategies').then((m) => m.EditStrategyRoute), under: 'builder' },
  stock: { path: patterns.stock, features: ['stock_pages'], load: () => import('./router/routes/stock').then((m) => m.StockRoute), under: 'overview' },
  attribution: { path: paths.attribution, features: [], load: () => import('@/features/attribution').then((m) => m.AttributionPage) },
} as const satisfies Record<string, PageEntry>

export type Page = keyof typeof PAGES
/** A page the navigation lists. */
export type ListedPage = { [K in Page]: (typeof PAGES)[K] extends { nav: object } ? K : never }[Page]
/** A page the phone's tab bar lists; its short name there is `common:nav.tab.<key>`. */
export type TabPage = { [K in Page]: (typeof PAGES)[K] extends { nav: { tab: true } } ? K : never }[Page]

export const pageEntries = Object.entries(PAGES) as [Page, PageEntry][]

/**
 * Features that open no page. Ordering on SinoPac acts inside pages other features open, and the server's answers
 * carry it. Naming it at a page would open that page to a viewer who sees ordering alone.
 */
export const FEATURES_WITHOUT_PAGE = ['sinopac_ordering'] as const satisfies readonly Feature[]
