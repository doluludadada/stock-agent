import { Activity, Calculator, Layers, LayoutDashboard, Settings2, Sparkles, Star, UsersRound, Wallet, type LucideIcon } from 'lucide-react'
import type { Schemas } from '@/shared/api'
import { paths } from '@/shared/config/paths'

type Permission = Schemas['Permission']

export interface NavItem {
  key: 'overview' | 'valuation' | 'watchlist' | 'account' | 'runs' | 'strategies' | 'builder' | 'users' | 'admin'
  to: string
  icon: LucideIcon
  /** Active only on this exact path, not on the paths under it. */
  end: boolean
  /** Shown only to a user whose role has this permission; the server checks it again on every request. */
  needs?: Permission
}

export interface NavSection {
  key: 'research' | 'mine' | 'admin'
  items: readonly NavItem[]
}

const OVERVIEW: NavItem = { key: 'overview', to: paths.overview, icon: LayoutDashboard, end: true }
const WATCHLIST: NavItem = { key: 'watchlist', to: paths.watchlist, icon: Star, end: false }
const ACCOUNT: NavItem = { key: 'account', to: paths.account, icon: Wallet, end: false }

const SECTIONS: readonly NavSection[] = [
  { key: 'research', items: [OVERVIEW, { key: 'valuation', to: paths.valuation, icon: Calculator, end: false }] },
  {
    key: 'mine',
    items: [
      WATCHLIST,
      ACCOUNT,
      { key: 'runs', to: paths.runs, icon: Activity, end: false },
      { key: 'strategies', to: paths.strategies, icon: Layers, end: true },
      { key: 'builder', to: paths.newStrategy, icon: Sparkles, end: false },
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

/** The sections a viewer with these permissions sees; a section with nothing left disappears. */
export function navSections(permissions: readonly Permission[]): NavSection[] {
  return SECTIONS.map((section) => ({ ...section, items: section.items.filter((item) => !item.needs || permissions.includes(item.needs)) })).filter(
    (section) => section.items.length > 0,
  )
}

/** The phone's tab bar: the three places used during a session; search and the other pages sit between and after them. */
export const TAB_PAGES = { market: OVERVIEW, watchlist: WATCHLIST, account: ACCOUNT } as const

/** The tab that holds a path; a stock page belongs to the market. */
export function isInTab(item: NavItem, pathname: string): boolean {
  return item.to === paths.overview ? pathname === paths.overview || pathname.startsWith('/stocks/') : pathname.startsWith(item.to)
}
