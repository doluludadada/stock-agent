import { Activity, Calculator, Layers, LayoutDashboard, Settings2, SlidersHorizontal, Sparkles, Star, UsersRound, Wallet, type LucideIcon } from 'lucide-react'
import type { Schemas } from '@/shared/api'
import { paths } from '@/shared/config/paths'

type Permission = Schemas['Permission']

export interface NavItem {
  key: 'overview' | 'valuation' | 'watchlist' | 'account' | 'settings' | 'runs' | 'strategies' | 'builder' | 'users' | 'admin'
  to: string
  icon: LucideIcon
  /** Active only on this exact path, not on the paths under it. */
  end: boolean
  /** Active too on the paths under this prefix: a run belongs to the analysis, a stock page to the market. */
  alsoUnder?: string
  /** Shown only to a user whose role has this permission; the server checks it again on every request. */
  needs?: Permission
}

export interface NavSection {
  key: 'analysis' | 'research' | 'mine' | 'admin'
  items: readonly NavItem[]
}

const RUNS: NavItem = { key: 'runs', to: paths.runs, icon: Activity, end: true, alsoUnder: '/runs/' }
const OVERVIEW: NavItem = { key: 'overview', to: paths.market, icon: LayoutDashboard, end: true, alsoUnder: '/stocks/' }
const WATCHLIST: NavItem = { key: 'watchlist', to: paths.watchlist, icon: Star, end: false }
const ACCOUNT: NavItem = { key: 'account', to: paths.account, icon: Wallet, end: false }

const SECTIONS: readonly NavSection[] = [
  {
    key: 'analysis',
    items: [
      RUNS,
      { key: 'strategies', to: paths.strategies, icon: Layers, end: true },
      { key: 'builder', to: paths.newStrategy, icon: Sparkles, end: false },
    ],
  },
  { key: 'research', items: [OVERVIEW, { key: 'valuation', to: paths.valuation, icon: Calculator, end: false }] },
  { key: 'mine', items: [WATCHLIST, ACCOUNT, { key: 'settings', to: paths.mySettings, icon: SlidersHorizontal, end: true }] },
  {
    key: 'admin',
    items: [
      { key: 'users', to: paths.users, icon: UsersRound, end: false, needs: 'manage_users' },
      { key: 'admin', to: paths.adminSettings, icon: Settings2, end: false, needs: 'edit_system_settings' },
    ],
  },
]

/** The sections a viewer with these permissions sees; a section with nothing left disappears. */
export function navSections(permissions: readonly Permission[]): NavSection[] {
  return SECTIONS.map((section) => ({ ...section, items: section.items.filter((item) => !item.needs || permissions.includes(item.needs)) })).filter(
    (section) => section.items.length > 0,
  )
}

/** The phone's tab bar: the four places used during a session; search and the other pages sit between and after them. */
export const TAB_PAGES = { analysis: RUNS, market: OVERVIEW, watchlist: WATCHLIST, account: ACCOUNT } as const

/** Whether a path is the item's page: the sidebar, the more sheet and the tab bar all mark the same item. */
export function isCurrent(item: NavItem, pathname: string): boolean {
  const own = item.end ? pathname === item.to : pathname.startsWith(item.to)
  return own || (item.alsoUnder !== undefined && pathname.startsWith(item.alsoUnder))
}
