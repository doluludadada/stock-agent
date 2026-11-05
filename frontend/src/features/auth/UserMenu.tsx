import { ChevronDown, LogIn, LogOut, Settings2, UsersRound } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { useTranslation } from '@/i18n'
import { hasPermission, useSession } from '@/shared/api'
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

interface UserMenuProps {
  /** The administrator's pages; a user without the permission never sees them. */
  adminLinks: { users: string; settings: string }
  onSignedOut: () => void
}

/** The header's account control: who is signed in, their role, the admin pages and sign-out; sign-in otherwise. */
export function UserMenu({ adminLinks, onSignedOut }: UserMenuProps) {
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
  const manageUsers = hasPermission(current, 'manage_users')
  const editSettings = hasPermission(current, 'edit_system_settings')
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
        {(manageUsers || editSettings) && <DropdownMenuSeparator />}
        {manageUsers && (
          <DropdownMenuItem asChild>
            <Link to={adminLinks.users}>
              <UsersRound aria-hidden />
              {t('menu.users')}
            </Link>
          </DropdownMenuItem>
        )}
        {editSettings && (
          <DropdownMenuItem asChild>
            <Link to={adminLinks.settings}>
              <Settings2 aria-hidden />
              {t('menu.settings')}
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={signOut.isPending} onSelect={() => signOut.mutate(undefined, { onSuccess: onSignedOut })}>
          <LogOut aria-hidden />
          {t('menu.signOut')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
