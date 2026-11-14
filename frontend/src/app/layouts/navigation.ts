import type { LucideIcon } from 'lucide-react'
import { matchPath } from 'react-router'
import { allows, shows, useAudience, useAuthStatus, useSession, type Audience, type Permission, type Visibilities } from '@/shared/api'
import { FOLDED_SECTIONS, pageEntries, SECTIONS, type ListedPage, type PageEntry, type SectionKey } from '../pages'

export interface NavItem {
  key: ListedPage
  to: string
  icon: LucideIcon
  tab: boolean
  menu: boolean
}

export interface NavSection {
  key: SectionKey
  folded: boolean
  items: readonly NavItem[]
}

export interface Viewer {
  permissions: readonly Permission[]
  audience: Audience | undefined
  /** Undefined until the server has said, which hides every page that names a feature. */
  visibilities: Visibilities | undefined
}

function shown(page: PageEntry, { permissions, audience, visibilities }: Viewer): boolean {
  return (
    (!page.needs || permissions.includes(page.needs)) &&
    (!page.requires || allows(audience, page.requires)) &&
    (page.features.length === 0 || page.features.some((feature) => shows(visibilities, permissions, feature)))
  )
}

/** The sections this viewer sees on this site, from the page table; a section with nothing left disappears. */
export function navSections(viewer: Viewer): NavSection[] {
  return SECTIONS.map((key) => ({
    key,
    folded: FOLDED_SECTIONS.includes(key),
    items: pageEntries.flatMap(([page, entry]) =>
      entry.nav?.section === key && shown(entry, viewer) ? [{ key: page as ListedPage, to: entry.path, icon: entry.nav.icon, tab: entry.nav.tab === true, menu: entry.nav.menu === true }] : [],
    ),
  })).filter((section) => section.items.length > 0)
}

export function useNavSections(): NavSection[] {
  const current = useSession()
  const audience = useAudience()
  const status = useAuthStatus()
  return navSections({ permissions: current.status === 'signedIn' ? current.user.permissions : [], audience: audience.data, visibilities: status.data?.features })
}

/** The listed page an address belongs to: its own, or the one it sits under (a stock page under the market). */
export function listedPageAt(pathname: string): string | null {
  const found = pageEntries.find(([, page]) => matchPath(page.path, pathname))
  return found ? (found[1].under ?? found[0]) : null
}

export function holdsCurrent(section: NavSection, pathname: string): boolean {
  const current = listedPageAt(pathname)
  return section.items.some((item) => item.key === current)
}

/** A folded section shows its pages once the reader opened it, and while the reader is on one of them. */
export function showsItems(section: NavSection, opened: readonly SectionKey[], pathname: string): boolean {
  return !section.folded || opened.includes(section.key) || holdsCurrent(section, pathname)
}
