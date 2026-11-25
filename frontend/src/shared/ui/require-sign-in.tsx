import { Briefcase, ListOrdered, LogIn, ShieldCheck, Star, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router'
import { useTranslation } from '@/i18n'
import { hasPermission, useAuthStatus, useSession, type Permission } from '@/shared/api'
import { paths } from '@/shared/config/paths'
import { cn } from '@/shared/lib/utils'
import { Button } from './button'
import { Skeleton } from './skeleton'
import { StateBlock } from './state-block'

/** The sign-in page, coming back to this page afterwards, and the register page, null while the server takes no registrations. */
export function useAuthLinks(): { signIn: string; register: string | null } {
  const location = useLocation()
  const status = useAuthStatus()
  return { signIn: paths.signInThen(`${location.pathname}${location.search}`), register: status.data?.registration_open === false ? null : paths.register }
}

/** The sign-in and register buttons, returning to the current page after sign-in. */
export function SignInActions({ size = 'default' }: { size?: 'default' | 'sm' }) {
  const { t } = useTranslation()
  const links = useAuthLinks()
  return (
    <>
      <Button asChild size={size}>
        <Link to={links.signIn}>
          <LogIn aria-hidden />
          {t('auth.signIn')}
        </Link>
      </Button>
      {links.register && (
        <Button asChild size={size} variant="outline">
          <Link to={links.register}>{t('auth.register')}</Link>
        </Button>
      )}
    </>
  )
}

interface RequireSignInProps {
  /** An administrator's page also needs this permission of the user's role. */
  needs?: Permission
  /** What signing in opens, as the prompt's title. */
  reason?: string
  /** A whole page also lists what an account holds; a card inside a page says only the reason. */
  layout?: 'page' | 'card'
  children: ReactNode
  className?: string
}

const ACCOUNT_HOLDS = [
  { key: 'ranking', icon: ListOrdered },
  { key: 'holdings', icon: Briefcase },
  { key: 'watchlist', icon: Star },
] as const

/** Said to a signed-in user without the permission, and where the server answers `administrators_only`. */
export function AdministratorsOnly({ layout = 'card', className }: Pick<RequireSignInProps, 'layout' | 'className'>) {
  const { t } = useTranslation()
  return <StateBlock icon={ShieldCheck} title={t('auth.adminOnly.title')} description={t('auth.adminOnly.description')} className={cn(layout === 'page' && 'rounded-2xl border bg-card py-12', className)} />
}

/**
 * Shows `children` to a signed-in user (with the permission, when one is named); otherwise says what signing in
 * opens, or that the page is for administrators. The server checks every request again: this only explains.
 */
export function RequireSignIn({ needs, reason, layout = 'card', children, className }: RequireSignInProps) {
  const { t } = useTranslation()
  const current = useSession()
  if (current.status === 'signedIn' && (!needs || hasPermission(current, needs))) return children
  if (current.status === 'checking') return <Skeleton className={cn('h-40 rounded-2xl', className)} />
  if (current.status === 'signedIn') return <AdministratorsOnly layout={layout} className={className} />
  const prompt = (
    <StateBlock
      icon={UserRound}
      title={current.ended ? t('auth.ended.title') : (reason ?? t('auth.prompt.title'))}
      description={current.ended ? t('auth.ended.description') : t('auth.prompt.description')}
      className={layout === 'card' ? className : 'py-10 md:items-start md:px-10 md:text-left [&>div]:md:justify-start'}
      action={<SignInActions />}
    />
  )
  if (layout === 'card') return prompt
  return (
    <section className={cn('grid overflow-hidden rounded-2xl border bg-card shadow-card md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]', className)}>
      {prompt}
      <div className="border-t bg-muted/40 px-6 py-8 md:border-t-0 md:border-l md:px-10">
        <p className="eyebrow mb-4">{t('auth.prompt.holds')}</p>
        <ul className="grid gap-4">
          {ACCOUNT_HOLDS.map((item) => (
            <li key={item.key} className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
                <item.icon aria-hidden className="size-4.5" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{t(`nav.${item.key}`)}</span>
                <span className="block text-xs text-pretty text-muted-foreground">{t(`auth.prompt.what.${item.key}`)}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
