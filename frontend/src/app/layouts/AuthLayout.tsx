import { LineChart, Star, Wallet } from 'lucide-react'
import { Outlet } from 'react-router'
import { useTranslation } from '@/i18n'
import { BrandMark } from './BrandMark'
import { PreferenceMenu } from './PreferenceMenu'
import { SiteFooter } from './SiteFooter'

const POINTS = [
  { key: 'market', icon: LineChart },
  { key: 'watchlist', icon: Star },
  { key: 'account', icon: Wallet },
] as const

/** Setup, sign-in and registration: the form alone on a phone, beside what the site offers on a wide screen. */
export function AuthLayout() {
  const { t } = useTranslation('auth')
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <aside className="hidden flex-col justify-between border-r bg-card p-10 lg:flex xl:p-14">
        <BrandMark />
        <div className="max-w-md space-y-8">
          <h2 className="text-3xl leading-tight font-semibold tracking-tight text-balance">{t('intro.title')}</h2>
          <ul className="space-y-5">
            {POINTS.map((point) => (
              <li key={point.key} className="flex items-start gap-3.5">
                <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
                  <point.icon aria-hidden className="size-4.5" />
                </span>
                <span className="pt-1.5 text-sm text-pretty text-muted-foreground">{t(`intro.points.${point.key}`)}</span>
              </li>
            ))}
          </ul>
        </div>
        <TrendArt />
      </aside>
      <div className="flex min-h-dvh flex-col">
        <header className="flex h-(--topbar-height) items-center justify-between gap-2 px-4 md:px-8">
          <BrandMark className="lg:invisible" />
          <PreferenceMenu />
        </header>
        <main id="main" className="flex flex-1 justify-center px-5 pt-6 pb-14 sm:items-center sm:pt-0 md:px-8">
          <Outlet />
        </main>
        <SiteFooter className="mx-5 mb-5 md:mx-8" />
      </div>
    </div>
  )
}

/** A quiet drawing of a rising close, the only picture on the page. */
function TrendArt() {
  return (
    <svg viewBox="0 0 400 120" aria-hidden className="h-28 w-full max-w-md text-brand">
      <defs>
        <linearGradient id="auth-trend-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.16" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M0 96 C40 90 60 70 96 76 S150 98 186 72 S240 30 276 46 S340 34 400 12 L400 120 L0 120 Z" fill="url(#auth-trend-fill)" />
      <path d="M0 96 C40 90 60 70 96 76 S150 98 186 72 S240 30 276 46 S340 34 400 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}
