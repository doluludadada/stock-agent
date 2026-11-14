import { ChevronDown, Ellipsis, Search, WifiOff } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router'
import { UserMenu } from '@/features/auth'
import { useTranslation } from '@/i18n'
import { useShows } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useOnline } from '@/shared/lib/use-online'
import { cn } from '@/shared/lib/utils'
import { PageSectionProvider } from '@/shared/ui/page-header'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/shared/ui/sheet'
import type { TabPage } from '../pages'
import { BrandMark } from './BrandMark'
import { holdsCurrent, listedPageAt, showsItems, useNavSections, type NavItem, type NavSection } from './navigation'
import { PreferenceControls, PreferenceMenu } from './PreferenceMenu'
import { SiteFooter } from './SiteFooter'
import { SearchField, SearchPalette } from './StockSearch'
import { useOpenedSections } from './use-opened-sections'

/** One shell for every width: a tab bar on a phone, a rail of icons on a tablet, the full sidebar on a desktop. */
export function AppShell() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const [searching, setSearching] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const sections = useNavSections()
  const searchable = useShows('stock_pages')
  const pages = sections.flatMap((item) => item.items)
  const folds = useOpenedSections()
  const section = sections.find((item) => holdsCurrent(item, location.pathname))

  const main = useRef<HTMLElement>(null)
  const arrivedAt = useRef(location.pathname)
  useEffect(() => {
    window.scrollTo({ top: 0 })
    // A keyboard or a screen reader starts at the new page, not at the link that led to it.
    if (arrivedAt.current !== location.pathname) main.current?.focus({ preventScroll: true })
    arrivedAt.current = location.pathname
  }, [location.pathname])

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[var(--rail-width)_minmax(0,1fr)] lg:grid-cols-[var(--sidebar-width)_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        {t('skipToContent')}
      </a>

      <aside className="hidden border-r bg-sidebar md:block">
        <div className="sticky top-0 flex h-dvh flex-col">
          <div className="flex h-(--topbar-height) items-center justify-center px-3 lg:justify-start lg:px-4">
            <BrandMark compact className="lg:hidden" />
            <BrandMark className="hidden lg:flex" />
          </div>
          <nav aria-label={t('nav.label')} className="flex-1 overflow-y-auto px-2 pt-2 pb-6 lg:px-3">
            <NavList sections={sections} folds={folds} variant="side" />
          </nav>
        </div>
      </aside>

      <div className="flex min-h-dvh min-w-0 flex-col">
        <header className="sticky top-0 z-20 flex h-(--topbar-height) items-center gap-2 border-b bg-background/85 px-4 backdrop-blur-md md:px-6 lg:px-8">
          <div className="md:hidden">
            <BrandMark />
          </div>
          {searchable && <SearchField onOpen={() => setSearching(true)} className="hidden md:flex" />}
          <div className="ml-auto flex items-center gap-1">
            <PreferenceMenu />
            <UserMenu links={pages.filter((item) => item.menu).map((item) => ({ to: item.to, icon: item.icon, label: t(`nav.${item.key}`) }))} onSignedOut={() => navigate(paths.home)} />
          </div>
        </header>

        <main id="main" ref={main} tabIndex={-1} className="mx-auto w-full max-w-(--content-max) flex-1 px-4 pt-5 pb-8 outline-none md:px-6 md:pb-10 lg:px-8 lg:pt-7">
          <OfflineNotice />
          <PageSectionProvider value={section && section.key !== 'today' ? t(`nav.section.${section.key}`) : null}>
            <Outlet />
          </PageSectionProvider>
        </main>
        <SiteFooter className="mx-auto w-full max-w-(--content-max) px-4 pb-[calc(var(--tabbar-height)+env(safe-area-inset-bottom)+1.5rem)] md:px-6 md:pb-8 lg:px-8" />
      </div>

      <TabBar tabs={pages.filter((item) => item.tab)} onSearch={searchable ? () => setSearching(true) : null} onMore={() => setMoreOpen(true)} />
      <MoreSheet open={moreOpen} onOpenChange={setMoreOpen} sections={sections} folds={folds} />
      {searchable && <SearchPalette open={searching} onOpenChange={setSearching} sections={sections} />}
    </div>
  )
}

type Folds = ReturnType<typeof useOpenedSections>

/** The two places that list every page: the side column (a rail of icons under 1024 px) and the phone's sheet. */
const NAV_STYLE = {
  side: {
    root: 'space-y-5',
    section: 'space-y-1',
    fold: 'flex min-h-14 w-full flex-col-reverse items-center justify-center gap-1 px-1 text-center text-[0.6875rem] leading-tight lg:min-h-9 lg:flex-row lg:justify-between lg:px-2.5 lg:text-left lg:text-[length:var(--font-size-caption)]',
    heading: 'eyebrow hidden px-2.5 pb-1 lg:block',
    list: 'space-y-0.5',
    link: 'flex min-h-14 flex-col items-center justify-center gap-1 rounded-lg px-1 text-center text-[0.6875rem] leading-tight text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-h-9 lg:flex-row lg:justify-start lg:gap-2.5 lg:px-2.5 lg:text-left lg:text-sm',
    current: 'bg-brand-soft font-medium text-brand hover:bg-brand-soft hover:text-brand',
    icon: 'size-5 shrink-0 lg:size-4',
  },
  sheet: {
    root: 'space-y-5',
    section: '',
    fold: '-mx-2 mb-2 flex min-h-11 w-[calc(100%+1rem)] items-center justify-between px-2',
    heading: 'eyebrow mb-2',
    list: 'grid grid-cols-2 gap-2',
    link: 'flex min-h-12 items-center gap-2.5 rounded-xl border bg-background px-3 text-sm',
    current: 'border-brand/30 bg-brand-soft font-medium text-brand',
    icon: 'size-4.5 shrink-0',
  },
} as const

interface NavListProps {
  sections: readonly NavSection[]
  folds: Folds
  variant: keyof typeof NAV_STYLE
  onNavigate?: () => void
}

/**
 * Every section with its pages. A folded section's name is the button that opens it; while the reader is on one of
 * its pages it stays open and the button rests, so the page's own entry never hides.
 */
function NavList({ sections, folds, variant, onNavigate }: NavListProps) {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const style = NAV_STYLE[variant]
  const current = listedPageAt(pathname)
  return (
    <div className={style.root}>
      {sections.map((section, index) => {
        const listId = `${variant}-${section.key}`
        const held = holdsCurrent(section, pathname)
        const open = showsItems(section, folds.opened, pathname)
        return (
          <div key={section.key} className={style.section}>
            {variant === 'side' && index > 0 && <div aria-hidden className="mx-3 mb-2 border-t lg:hidden" />}
            {section.key === 'today' ? null : section.folded ? (
              <button
                type="button"
                aria-expanded={open}
                aria-controls={listId}
                disabled={held}
                onClick={() => folds.toggle(section.key)}
                className={cn('eyebrow rounded-lg transition-colors enabled:hover:bg-muted enabled:hover:text-foreground', style.fold)}
              >
                {t(`nav.section.${section.key}`)}
                {!held && <ChevronDown aria-hidden className={cn('size-4 shrink-0 transition-transform', open && 'rotate-180')} />}
              </button>
            ) : (
              <p className={style.heading}>{t(`nav.section.${section.key}`)}</p>
            )}
            <ul id={listId} hidden={!open} className={style.list}>
              {section.items.map((item) => (
                <li key={item.key}>
                  <Link to={item.to} aria-current={item.key === current ? 'page' : undefined} onClick={onNavigate} className={cn(style.link, item.key === current && style.current)}>
                    <item.icon aria-hidden className={style.icon} />
                    {t(`nav.${item.key}`)}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

const TABS_BEFORE_SEARCH = 2
const tabClass = 'flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 text-[0.6875rem] font-medium transition-colors'

function TabLink({ item, current }: { item: NavItem; current: boolean }) {
  const { t } = useTranslation()
  return (
    <Link to={item.to} aria-current={current ? 'page' : undefined} className={cn(tabClass, current ? 'text-brand' : 'text-muted-foreground')}>
      <item.icon aria-hidden className="size-5" />
      {t(`nav.tab.${item.key as TabPage}`)}
    </Link>
  )
}

/** The phone's bottom bar: the listed pages marked `tab`, the search between them, and everything else behind "more". */
function TabBar({ tabs, onSearch, onMore }: { tabs: readonly NavItem[]; onSearch: (() => void) | null; onMore: () => void }) {
  const { t } = useTranslation()
  const current = listedPageAt(useLocation().pathname)
  const links = tabs.map((item) => <TabLink key={item.key} item={item} current={item.key === current} />)
  return (
    <nav
      aria-label={t('nav.tabs')}
      className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-background/92 px-1 pb-[env(safe-area-inset-bottom)] shadow-bar backdrop-blur-md md:hidden"
    >
      <div className="flex h-(--tabbar-height) w-full items-stretch">
        {links.slice(0, TABS_BEFORE_SEARCH)}
        {onSearch && (
          <button type="button" onClick={onSearch} className={cn(tabClass, 'text-muted-foreground')}>
            <span className="grid size-9 place-items-center rounded-full bg-brand text-primary-foreground shadow-card">
              <Search aria-hidden className="size-4.5" />
            </span>
            <span className="sr-only">{t('nav.tab.search')}</span>
          </button>
        )}
        {links.slice(TABS_BEFORE_SEARCH)}
        <button type="button" onClick={onMore} aria-haspopup="dialog" className={cn(tabClass, tabs.some((item) => item.key === current) ? 'text-muted-foreground' : 'text-brand')}>
          <Ellipsis aria-hidden className="size-5" />
          {t('nav.tab.more')}
        </button>
      </div>
    </nav>
  )
}

/** Every page, the language and the theme, in a sheet that rises from the tab bar. */
function MoreSheet({ open, onOpenChange, sections, folds }: { open: boolean; onOpenChange: (open: boolean) => void; sections: NavSection[]; folds: Folds }) {
  const { t } = useTranslation()
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="max-h-[85dvh] gap-0 overflow-y-auto rounded-t-2xl bg-card pb-[calc(env(safe-area-inset-bottom)+1rem)]">
        <SheetHeader className="pb-2">
          <SheetTitle>{t('nav.moreTitle')}</SheetTitle>
          <SheetDescription className="sr-only">{t('nav.label')}</SheetDescription>
        </SheetHeader>
        <nav aria-label={t('nav.label')} className="space-y-5 px-4">
          <NavList sections={sections} folds={folds} variant="sheet" onNavigate={() => onOpenChange(false)} />
          <div>
            <p className="eyebrow mb-2">{t('preferences.title')}</p>
            <PreferenceControls />
          </div>
        </nav>
      </SheetContent>
    </Sheet>
  )
}

function OfflineNotice() {
  const { t } = useTranslation()
  const online = useOnline()
  return (
    <div aria-live="polite">
      {!online && (
        <p className="mb-4 flex items-center gap-2 rounded-lg border border-gold/40 bg-gold-soft px-3 py-2 text-sm">
          <WifiOff aria-hidden className="size-4 shrink-0 text-gold" />
          {t('offline')}
        </p>
      )}
    </div>
  )
}
