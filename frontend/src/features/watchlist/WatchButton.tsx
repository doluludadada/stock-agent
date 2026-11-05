import { Star } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { useIsSignedIn } from '@/shared/api'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { useAuthLinks } from '@/shared/ui/require-sign-in'
import { isManuallyWatched, useWatchlistChange, useWatchlistEntries } from './api'

interface WatchButtonProps {
  code: string
  label: string
  variant?: 'icon' | 'full'
  className?: string
}

/** Toggles the stock on the user's MANUAL watchlist on the server; signed out, it leads to sign-in and back. */
export function WatchButton({ code, label, variant = 'full', className }: WatchButtonProps) {
  const { t } = useTranslation('watchlist')
  const signedIn = useIsSignedIn()
  const links = useAuthLinks()
  const location = useLocation()
  const entries = useWatchlistEntries()
  const change = useWatchlistChange()
  const watched = isManuallyWatched(entries.data, code)

  if (!signedIn && links) {
    return (
      <Button asChild variant={variant === 'icon' ? 'ghost' : 'outline'} size={variant === 'icon' ? 'icon' : 'default'} className={className}>
        <Link to={links.signIn(`${location.pathname}${location.search}`)} aria-label={variant === 'icon' ? t('action.signInToWatch', { name: label }) : undefined}>
          <Star aria-hidden className="size-4" />
          {variant === 'full' && t('action.signInToWatch', { name: label })}
        </Link>
      </Button>
    )
  }

  const toggle = () => {
    const action = watched ? 'remove' : 'add'
    change.mutate(
      { action, stockIds: [code] },
      {
        onSuccess: () => toast.success(t(watched ? 'toast.removed' : 'toast.added', { name: label })),
        onError: (error) => toast.error(t('toast.failed', { reason: error.message })),
      },
    )
  }

  const text = t(watched ? 'action.watching' : 'action.add')
  return variant === 'icon' ? (
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-pressed={watched}
        aria-label={`${text}: ${label}`}
        onClick={toggle}
        disabled={change.isPending}
        className={cn('text-muted-foreground hover:text-gold', watched && 'text-gold', className)}
      >
        <Star aria-hidden className={cn('size-4 transition-transform', watched && 'scale-110 fill-current')} />
      </Button>
    ) : (
      <Button
        type="button"
        variant={watched ? 'secondary' : 'outline'}
        aria-pressed={watched}
        onClick={toggle}
        disabled={change.isPending}
        className={cn(watched && 'border-gold/40 text-gold', className)}
      >
        <Star aria-hidden className={cn('size-4', watched && 'fill-current')} />
        {text}
      </Button>
    )
}
