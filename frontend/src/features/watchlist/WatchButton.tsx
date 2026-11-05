import { Star } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from '@/i18n'
import { useSession } from '@/shared/api'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { UnlockDialog } from '@/shared/ui/unlock'
import { isManuallyWatched, useWatchlistChange, useWatchlistEntries } from './api'

interface WatchButtonProps {
  code: string
  label: string
  variant?: 'icon' | 'full'
  className?: string
}

/** Toggles the stock on the MANUAL watchlist on the server; while locked it asks for the token first. */
export function WatchButton({ code, label, variant = 'full', className }: WatchButtonProps) {
  const { t } = useTranslation('watchlist')
  const { unlocked } = useSession('owner')
  const entries = useWatchlistEntries()
  const change = useWatchlistChange()
  const [unlocking, setUnlocking] = useState(false)
  const watched = isManuallyWatched(entries.data, code)

  const toggle = () => {
    if (!unlocked) return setUnlocking(true)
    const action = watched ? 'remove' : 'add'
    change.mutate(
      { action, stockIds: [code] },
      {
        onSuccess: () => toast.success(t(watched ? 'toast.removed' : 'toast.added', { name: label })),
        onError: (error) => toast.error(t('toast.failed', { reason: error.message })),
      },
    )
  }

  const text = t(watched ? 'action.remove' : 'action.add')
  const button =
    variant === 'icon' ? (
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
  return (
    <>
      {button}
      <UnlockDialog scope="owner" open={unlocking} onOpenChange={setUnlocking} />
    </>
  )
}
