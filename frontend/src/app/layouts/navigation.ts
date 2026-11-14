import { Activity, Briefcase, Calculator, CandlestickChart, History, Home, Landmark, Layers, ListOrdered, Settings2, SlidersHorizontal, Sparkles, Star, UsersRound, Wallet, type LucideIcon } from 'lucide-react'
import { allows, shows, type Audience, type Capability, type Feature, type Schemas, type Visibilities } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { PAGE_FEATURES, type Page } from '../pages'

type Permission = Schemas['Permission']

export interface NavItem {
  key: Extract<Page, 'home' | 'overview' | 'valuation' | 'watchlist' | 'holdings' | 'account' | 'brokerage' | 'settings' | 'runs' | 'strategies' | 'backtest' | 'ranking' | 'builder' | 'users' | 'admin'>
  to: string
  icon: LucideIcon
  /** Active only on this exact path, not on the paths under it. */
  end: boolean
  /** Active too on the paths under this prefix: a stock page belongs to the market, a strategy being edited to the designer. */
  alsoUnder?: string
  /** Shown only to a user whose role has this permission; the server checks it again on every request. */
  needs?: Permission
  /** Shown only on a site whose audience allows this; the server refuses it elsewhere. */
  requires?: Capability
}

export interface NavSection {
  key: 'today' | 'research' | 'mine' | 'tools' | 'admin'
  items: readonly NavItem[]
  /**
   * Folded away until the reader opens it: pages that are kept but are no longer where the app's attention is. It
   * says why in a note (`nav.note.<key>`), and shows open while the reader is on one of its pages.
   */
  folded?: true
}

const HOME: NavItem = { key: 'home', to: paths.home, icon: Home, end: true }
const RANKING: NavItem = { key: 'ranking', to: paths.ranking, icon: ListOrdered, end: false }
const OVERVIEW: NavItem = { key: 'overview', to: paths.market, icon: CandlestickChart, end: false, alsoUnder: '/stocks/' }
const WATCHLIST: NavItem = { key: 'watchlist', to: paths.watchlist, icon: Star, end: false }
const HOLDINGS: NavItem = { key: 'holdings', to: paths.holdings, icon: Briefcase, end: false }
// The SinoPac account's address sits under the mock account's, so the mock account marks its exact path only.
const ACCOUNT: NavItem = { key: 'account', to: paths.account, icon: Wallet, end: true }
const BROKERAGE: NavItem = { key: 'brokerage', to: paths.brokerage, icon: Landmark, end: false, needs: 'use_real_broker' }

/**
 * The order is the product's: the home page, then what has evidence (the ranking, with the market around it), then
 * what is the reader's own. The tools kept for the administrator (analysis runs, the technical strategies, valuation
 * and the mock account they trade on) fold away under one name.
 */
const SECTIONS: readonly NavSection[] = [
  { key: 'today', items: [HOME] },
  { key: 'research', items: [RANKING, OVERVIEW] },
  { key: 'mine', items: [HOLDINGS, WATCHLIST, BROKERAGE, { key: 'settings', to: paths.mySettings, icon: SlidersHorizontal, end: true }] },
  {
    key: 'tools',
    folded: true,
    items: [
      { key: 'runs', to: paths.runs, icon: Activity, end: false },
      ACCOUNT,
      { key: 'valuation', to: paths.valuation, icon: Calculator, end: false, requires: 'mops' },
      { key: 'strategies', to: paths.strategies, icon: Layers, end: true },
      { key: 'backtest', to: paths.backtest, icon: History, end: false },
      { key: 'builder', to: paths.newStrategy, icon: Sparkles, end: false, alsoUnder: '/strategies/' },
    ],
  },
  {
    key: 'admin',
    items: [
      { key: 'users', to: paths.users, icon: UsersRound, end: false, needs: 'manage_users' },
      { key: 'admin', to: paths.adminSettings, icon: Settings2, end: false, needs: 'edit_system_settings' },
    ],
  },
]

/** The features a page belongs to; the site shows its entry to a viewer who sees any one of them. */
export function featuresOf(item: NavItem): readonly Feature[] {
  return PAGE_FEATURES[item.key]
}

export interface Viewer {
  permissions: readonly Permission[]
  audience: Audience | undefined
  /** Whom the site shows each feature to; undefined until the server has said, which hides every page that names one. */
  visibilities: Visibilities | undefined
}

function shown(item: NavItem, { permissions, audience, visibilities }: Viewer): boolean {
  const features = featuresOf(item)
  return (
    (!item.needs || permissions.includes(item.needs)) &&
    (!item.requires || allows(audience, item.requires)) &&
    (features.length === 0 || features.some((feature) => shows(visibilities, permissions, feature)))
  )
}

/** The sections this viewer sees on this site; a section with nothing left disappears. */
export function navSections(viewer: Viewer): NavSection[] {
  return SECTIONS.map((section) => ({ ...section, items: section.items.filter((item) => shown(item, viewer)) })).filter((section) => section.items.length > 0)
}

/** The phone's tab bar: the home page, the ranking and the holdings; search sits between them, every other page in the sheet after them. */
export const TAB_PAGES = { home: HOME, ranking: RANKING, holdings: HOLDINGS } as const

/** Whether a path is the item's page: the sidebar, the more sheet and the tab bar all mark the same item. */
export function isCurrent(item: NavItem, pathname: string): boolean {
  const own = item.end ? pathname === item.to : pathname.startsWith(item.to)
  return own || (item.alsoUnder !== undefined && pathname.startsWith(item.alsoUnder))
}

/** Whether a section's pages show: always, unless it is folded, the reader has not opened it and stands on none of its pages. */
export function showsItems(section: NavSection, opened: readonly NavSection['key'][], pathname: string): boolean {
  return !section.folded || opened.includes(section.key) || holdsCurrent(section, pathname)
}

/** Whether the reader is on one of the section's pages, which keeps a folded section open so the page's entry never hides. */
export function holdsCurrent(section: NavSection, pathname: string): boolean {
  return section.items.some((item) => isCurrent(item, pathname))
}
