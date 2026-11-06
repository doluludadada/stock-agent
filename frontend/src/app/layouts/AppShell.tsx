import { Ellipsis, Search, WifiOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router'
import { UserMenu } from '@/features/auth'
import { useTranslation } from '@/i18n'
import { useSession } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { useOnline } from '@/shared/lib/use-online'
import { cn } from '@/shared/lib/utils'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/shared/ui/sheet'
import { BrandMark } from './BrandMark'
import { isCurrent, navSections, TAB_PAGES, type NavItem, type NavSection } from './navigation'
import { PreferenceControls, PreferenceMenu } from './PreferenceMenu'
import { SearchField, SearchPalette } from './StockSearch'

/**
 * One shell for every width: a tab bar on a phone, a rail of icons on a tablet, the full sidebar on a desktop. The
 * side column is a grid cell as tall as the page, so its background never stops part way down.
 */
export function AppShell() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const current = useSession()
  const [searching, setSearching] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const sections = navSections(current.status === 'signedIn' ? current.user.permissions : [])

  useEffect(() => {
    window.scrollTo({ top: 0 })
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
            <SideNav sections={sections} />
          </nav>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex h-(--topbar-height) items-center gap-2 border-b bg-background/85 px-4 backdrop-blur-md md:px-6 lg:px-8">
          <div className="md:hidden">
            <BrandMark />
          </div>
          <SearchField onOpen={() => setSearching(true)} className="hidden md:flex" />
          <div className="ml-auto flex items-center gap-1">
            <PreferenceMenu />
            <UserMenu adminLinks={{ users: paths.users, settings: paths.adminSettings }} onSignedOut={() => navigate(paths.runs)} />
          </div>
        </header>

        <main
          id="main"
          tabIndex={-1}
          className="mx-auto w-full max-w-(--content-max) px-4 pt-5 pb-[calc(var(--tabbar-height)+env(safe-area-inset-bottom)+1.5rem)] outline-none md:px-6 md:pb-10 lg:px-8 lg:pt-7"
        >
          <OfflineNotice />
          <Outlet />
        </main>
      </div>

      <TabBar onSearch={() => setSearching(true)} onMore={() => setMoreOpen(true)} moreActive={!Object.values(TAB_PAGES).some((item) => isCurrent(item, location.pathname))} />
      <MoreSheet open={moreOpen} onOpenChange={setMoreOpen} sections={sections} />
      <SearchPalette open={searching} onOpenChange={setSearching} sections={sections} />
    </div>
  )
}

function SideNav({ sections }: { sections: NavSection[] }) {
  const { t } = useTranslation()
  const location = useLocation()
  return (
    <div className="space-y-5">
      {sections.map((section) => (
        <div key={section.key} className="space-y-1">
          <p className="eyebrow hidden px-2.5 pb-1 lg:block">{t(`nav.section.${section.key}`)}</p>
          <div aria-hidden className="mx-3 mb-2 border-t first:hidden lg:hidden" />
          <ul className="space-y-0.5">
            {section.items.map((item) => (
              <li key={item.key}>
                <Link
                  to={item.to}
                  aria-current={isCurrent(item, location.pathname) ? 'page' : undefined}
                  className={cn(
                    'group flex min-h-14 flex-col items-center justify-center gap-1 rounded-lg px-1 text-center text-[0.6875rem] leading-tight text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
                    'lg:min-h-9 lg:flex-row lg:justify-start lg:gap-2.5 lg:px-2.5 lg:text-left lg:text-sm',
                    isCurrent(item, location.pathname) && 'bg-brand-soft font-medium text-brand hover:bg-brand-soft hover:text-brand',
                  )}
                >
                  <item.icon aria-hidden className="size-5 shrink-0 lg:size-4" />
                  {t(`nav.${item.key}`)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

const tabClass = 'flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 text-[0.6875rem] font-medium transition-colors'

/** The phone's bottom bar: the analysis runs, the market, search, the watchlist, the account and everything else. */
function TabBar({ onSearch, onMore, moreActive }: { onSearch: () => void; onMore: () => void; moreActive: boolean }) {
  const { t } = useTranslation()
  const location = useLocation()
  const tab = (name: keyof typeof TAB_PAGES, item: NavItem) => {
    const active = isCurrent(item, location.pathname)
    return (
      <Link to={item.to} aria-current={active ? 'page' : undefined} className={cn(tabClass, active ? 'text-brand' : 'text-muted-foreground')}>
        <item.icon aria-hidden className={cn('size-5', active && name === 'watchlist' && 'fill-current')} />
        {t(`nav.tab.${name}`)}
      </Link>
    )
  }
  return (
    <nav
      aria-label={t('nav.tabs')}
      className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-background/92 px-1 pb-[env(safe-area-inset-bottom)] shadow-bar backdrop-blur-md md:hidden"
    >
      <div className="flex h-(--tabbar-height) w-full items-stretch">
        {tab('analysis', TAB_PAGES.analysis)}
        {tab('market', TAB_PAGES.market)}
        <button type="button" onClick={onSearch} className={cn(tabClass, 'text-muted-foreground')}>
          <span className="grid size-9 place-items-center rounded-full bg-brand text-primary-foreground shadow-card">
            <Search aria-hidden className="size-4.5" />
          </span>
          <span className="sr-only">{t('nav.tab.search')}</span>
        </button>
        {tab('watchlist', TAB_PAGES.watchlist)}
        {tab('account', TAB_PAGES.account)}
        <button type="button" onClick={onMore} aria-haspopup="dialog" className={cn(tabClass, moreActive ? 'text-brand' : 'text-muted-foreground')}>
          <Ellipsis aria-hidden className="size-5" />
          {t('nav.tab.more')}
        </button>
      </div>
    </nav>
  )
}

/** Every page, the language and the theme, in a sheet that rises from the tab bar. */
function MoreSheet({ open, onOpenChange, sections }: { open: boolean; onOpenChange: (open: boolean) => void; sections: NavSection[] }) {
  const { t } = useTranslation()
  const location = useLocation()
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="max-h-[85dvh] gap-0 overflow-y-auto rounded-t-2xl bg-card pb-[calc(env(safe-area-inset-bottom)+1rem)]">
        <SheetHeader className="pb-2">
          <SheetTitle>{t('nav.moreTitle')}</SheetTitle>
          <SheetDescription className="sr-only">{t('nav.label')}</SheetDescription>
        </SheetHeader>
        <nav aria-label={t('nav.label')} className="space-y-5 px-4">
          {sections.map((section) => (
            <div key={section.key}>
              <p className="eyebrow mb-2">{t(`nav.section.${section.key}`)}</p>
              <ul className="grid grid-cols-2 gap-2">
                {section.items.map((item) => (
                  <li key={item.key}>
                    <Link
                      to={item.to}
                      aria-current={isCurrent(item, location.pathname) ? 'page' : undefined}
                      onClick={() => onOpenChange(false)}
                      className={cn(
                        'flex min-h-12 items-center gap-2.5 rounded-xl border px-3 text-sm',
                        isCurrent(item, location.pathname) ? 'border-brand/30 bg-brand-soft font-medium text-brand' : 'bg-background',
                      )}
                    >
                      <item.icon aria-hidden className="size-4.5 shrink-0" />
                      {t(`nav.${item.key}`)}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
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
