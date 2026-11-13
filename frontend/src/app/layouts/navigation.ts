import { Activity, Calculator, History, Layers, LayoutDashboard, ListOrdered, Settings2, SlidersHorizontal, Sparkles, Star, UsersRound, Wallet, type LucideIcon } from 'lucide-react'
import { allows, type Audience, type Capability, type Schemas } from '@/shared/api'
import { paths } from '@/shared/config/paths'

type Permission = Schemas['Permission']

export interface NavItem {
  key: 'overview' | 'valuation' | 'watchlist' | 'account' | 'settings' | 'runs' | 'strategies' | 'backtest' | 'ranking' | 'builder' | 'users' | 'admin'
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
  key: 'research' | 'mine' | 'technical' | 'admin'
  items: readonly NavItem[]
  /**
   * Folded away until the reader opens it: pages that are kept but are no longer where the app's attention is. It
   * says why in a note (`nav.note.<key>`), and shows open while the reader is on one of its pages.
   */
  folded?: true
}

const RANKING: NavItem = { key: 'ranking', to: paths.ranking, icon: ListOrdered, end: false }
const OVERVIEW: NavItem = { key: 'overview', to: paths.market, icon: LayoutDashboard, end: true, alsoUnder: '/stocks/' }
const WATCHLIST: NavItem = { key: 'watchlist', to: paths.watchlist, icon: Star, end: false }
const ACCOUNT: NavItem = { key: 'account', to: paths.account, icon: Wallet, end: false }

const SECTIONS: readonly NavSection[] = [
  { key: 'research', items: [RANKING, OVERVIEW, { key: 'valuation', to: paths.valuation, icon: Calculator, end: false, requires: 'mops' }] },
  { key: 'mine', items: [WATCHLIST, ACCOUNT, { key: 'settings', to: paths.mySettings, icon: SlidersHorizontal, end: true }] },
  {
    key: 'technical',
    folded: true,
    items: [
      { key: 'runs', to: paths.runs, icon: Activity, end: false },
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

const shown = (item: NavItem, permissions: readonly Permission[], audience: Audience | undefined) =>
  (!item.needs || permissions.includes(item.needs)) && (!item.requires || allows(audience, item.requires))

/** The sections a viewer with these permissions sees on a site of this audience; a section with nothing left disappears. */
export function navSections(permissions: readonly Permission[], audience: Audience | undefined): NavSection[] {
  return SECTIONS.map((section) => ({ ...section, items: section.items.filter((item) => shown(item, permissions, audience)) })).filter(
    (section) => section.items.length > 0,
  )
}

/** The phone's tab bar: the four places used during a session; search and the other pages sit between and after them. */
export const TAB_PAGES = { ranking: RANKING, market: OVERVIEW, watchlist: WATCHLIST, account: ACCOUNT } as const

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
