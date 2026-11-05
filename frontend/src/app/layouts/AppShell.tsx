import {
  Activity,
  Calculator,
  Layers,
  LayoutDashboard,
  LockKeyhole,
  LockKeyholeOpen,
  Menu,
  Settings2,
  Sparkles,
  Star,
  Wallet,
  WifiOff,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { useTranslation } from '@/i18n'
import { session, useSession } from '@/shared/api'
import { useOnline } from '@/shared/lib/use-online'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/shared/ui/sheet'
import { UnlockDialog } from '@/shared/ui/unlock'
import { paths } from '@/shared/config/paths'
import { BrandMark } from './BrandMark'
import { PreferenceMenu } from './PreferenceMenu'
import { StockSearch } from './StockSearch'

const NAV = [
  { to: paths.overview, key: 'overview', icon: LayoutDashboard, end: true },
  { to: paths.strategies, key: 'strategies', icon: Layers, end: true },
  { to: paths.newStrategy, key: 'builder', icon: Sparkles, end: false },
  { to: paths.runs, key: 'runs', icon: Activity, end: false },
  { to: paths.valuation, key: 'valuation', icon: Calculator, end: false },
  { to: paths.watchlist, key: 'watchlist', icon: Star, end: false },
  { to: paths.account, key: 'account', icon: Wallet, end: false },
] as const

const ADMIN_NAV = [{ to: paths.adminSettings, key: 'admin', icon: Settings2, end: false }] as const

interface NavItem {
  to: string
  key: string
  icon: LucideIcon
  end: boolean
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <NavList items={NAV} onNavigate={onNavigate} />
      <div className="my-3 border-t" />
      <NavList items={ADMIN_NAV} onNavigate={onNavigate} />
    </>
  )
}

function NavList({ items, onNavigate }: { items: readonly NavItem[]; onNavigate?: () => void }) {
  const { t } = useTranslation()
  return (
    <ul className="space-y-0.5">
      {items.map((item) => (
        <li key={item.key}>
          <NavLink
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'group relative flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground',
                isActive && 'bg-sidebar-accent font-medium text-foreground',
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  aria-hidden
                  className={cn(
                    'absolute top-1/2 left-0 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary transition-opacity',
                    isActive ? 'opacity-100' : 'opacity-0',
                  )}
                />
                <item.icon aria-hidden className={cn('size-4', isActive && 'text-primary')} />
                {t(`nav.${item.key}`)}
              </>
            )}
          </NavLink>
        </li>
      ))}
    </ul>
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

/** Unlocks or locks the owner's private data for this tab. */
function SessionButton() {
  const { t } = useTranslation()
  const { unlocked } = useSession('owner')
  const [open, setOpen] = useState(false)
  if (unlocked) {
    return (
      <Button type="button" variant="ghost" size="sm" onClick={() => session.lock('owner')} aria-label={t('session.lock')} className="gap-1.5 text-jade">
        <LockKeyholeOpen aria-hidden className="size-4" />
        <span aria-hidden className="hidden md:inline">
          {t('session.unlocked')}
        </span>
      </Button>
    )
  }
  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)} aria-label={t('session.unlock')} className="gap-1.5">
        <LockKeyhole aria-hidden className="size-4" />
        <span aria-hidden className="hidden md:inline">
          {t('session.unlock')}
        </span>
      </Button>
      <UnlockDialog scope="owner" open={open} onOpenChange={setOpen} />
    </>
  )
}

export function AppShell() {
  const { t } = useTranslation()
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [location.pathname])

  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        {t('skipToContent')}
      </a>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-(--sidebar-width) flex-col border-r bg-sidebar lg:flex">
        <div className="flex h-(--topbar-height) items-center px-4">
          <BrandMark />
        </div>
        <nav aria-label={t('nav.label')} className="flex-1 overflow-y-auto px-2.5 py-3">
          <NavItems />
        </nav>
      </aside>

      <div className="lg:pl-(--sidebar-width)">
        <header className="sticky top-0 z-20 flex h-(--topbar-height) items-center gap-2 border-b bg-background/90 px-4 backdrop-blur sm:px-6">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMenuOpen(true)}
            aria-label={t('nav.open')}
          >
            <Menu aria-hidden className="size-5" />
          </Button>
          <div className="lg:hidden">
            <BrandMark compact />
          </div>
          <div className="flex flex-1 justify-end sm:justify-start">
            <StockSearch />
          </div>
          <SessionButton />
          <PreferenceMenu />
        </header>

        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-(--content-max) px-4 py-5 outline-none sm:px-6 lg:py-6">
          <OfflineNotice />
          <Outlet />
        </main>
      </div>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="w-72 bg-sidebar p-0">
          <SheetHeader className="border-b">
            <SheetTitle asChild>
              <div>
                <BrandMark />
              </div>
            </SheetTitle>
            <SheetDescription className="sr-only">{t('nav.label')}</SheetDescription>
          </SheetHeader>
          <nav aria-label={t('nav.label')} className="flex-1 px-2.5">
            <NavItems onNavigate={() => setMenuOpen(false)} />
          </nav>
        </SheetContent>
      </Sheet>
    </div>
  )
}
