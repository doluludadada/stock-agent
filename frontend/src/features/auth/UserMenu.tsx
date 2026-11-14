import { ChevronDown, LogIn, LogOut, type LucideIcon } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { useSession } from '@/shared/api'
import { cn } from '@/shared/lib/utils'
import { Avatar } from '@/shared/ui/avatar'
import { Button } from '@/shared/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/shared/ui/dropdown-menu'
import { useAuthLinks } from '@/shared/ui/require-sign-in'
import { Skeleton } from '@/shared/ui/skeleton'
import { useSignOut } from './api'
import type { Role } from './model'

export function RoleBadge({ kind, className }: { kind: Role; className?: string }) {
  const { t } = useTranslation('auth')
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center rounded-full px-2 text-xs font-medium whitespace-nowrap',
        kind === 'administrator' ? 'bg-brand-soft text-brand' : 'bg-muted text-muted-foreground',
        className,
      )}
    >
      {t(`role.${kind}`)}
    </span>
  )
}

export interface MenuLink {
  to: string
  icon: LucideIcon
  label: string
}

/** The header's account control: who is signed in, their role, the pages the shell lists here, and sign-out; sign-in otherwise. */
export function UserMenu({ links: pages, onSignedOut }: { links: readonly MenuLink[]; onSignedOut: () => void }) {
  const { t } = useTranslation('auth')
  const current = useSession()
  const links = useAuthLinks()
  const location = useLocation()
  const signOut = useSignOut()

  if (current.status === 'checking') return <Skeleton className="size-9 rounded-full" />
  if (current.status === 'signedOut') {
    if (!links) return null
    return (
      <div className="flex items-center gap-1.5">
        {links.register && (
          <Button asChild variant="ghost" size="sm" className="hidden md:inline-flex">
            <Link to={links.register}>{t('common:auth.register')}</Link>
          </Button>
        )}
        <Button asChild size="sm">
          <Link to={links.signIn(`${location.pathname}${location.search}`)}>
            <LogIn aria-hidden />
            {t('common:auth.signIn')}
          </Link>
        </Button>
      </div>
    )
  }

  const { user } = current
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" className="gap-2 rounded-full px-0 md:rounded-lg md:pr-2 md:pl-1" aria-label={t('menu.label', { name: user.username })}>
          <Avatar name={user.username} className="size-9 md:size-7" />
          <span aria-hidden className="hidden max-w-32 truncate text-sm font-medium md:inline">
            {user.username}
          </span>
          <ChevronDown aria-hidden className="hidden size-3.5 text-muted-foreground md:inline" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="flex items-center gap-3 py-2 font-normal">
          <Avatar name={user.username} className="size-10 text-base" />
          <span className="min-w-0 space-y-1">
            <span className="block truncate text-sm font-semibold text-foreground">{user.username}</span>
            <span className="block truncate text-xs text-muted-foreground">{user.email}</span>
            <RoleBadge kind={user.role} />
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {pages.map(({ to, icon: Icon, label }) => (
          <DropdownMenuItem key={to} asChild>
            <Link to={to}>
              <Icon aria-hidden />
              {label}
            </Link>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={signOut.isPending} onSelect={() => signOut.mutate(undefined, { onSuccess: onSignedOut, onError: () => toast.error(t('menu.signOutFailed')) })}>
          <LogOut aria-hidden />
          {t('menu.signOut')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
