import { CircleAlert, CircleCheck, CircleDashed, LoaderCircle } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import type { Run } from './api'

const LOOK = {
  running: { icon: LoaderCircle, tone: 'border-primary/40 text-primary', spin: true },
  finished: { icon: CircleCheck, tone: 'border-jade/40 text-jade', spin: false },
  failed: { icon: CircleAlert, tone: 'border-destructive/40 text-destructive', spin: false },
  unfinished: { icon: CircleDashed, tone: 'border-gold/40 text-gold', spin: false },
} as const

/** A run's real state from the server; there is no progress percentage because the server reports none. */
export function RunStateBadge({ state }: { state: Run['state'] }) {
  const { t } = useTranslation('runs')
  const { icon: Icon, tone, spin } = LOOK[state]
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs', tone)}>
      <Icon aria-hidden className={cn('size-3.5', spin && 'animate-spin motion-reduce:animate-none')} />
      {t(`state.${state}`)}
    </span>
  )
}
