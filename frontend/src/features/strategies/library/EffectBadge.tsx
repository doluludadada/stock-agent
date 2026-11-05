import { ShieldX, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import type { RuleEffect } from '../model/types'

const ICON = { block_on_fail: ShieldX, reduce_score_on_fail: ThumbsDown, increase_score_on_pass: ThumbsUp } as const
const TONE = {
  block_on_fail: 'border-destructive/30 text-destructive',
  reduce_score_on_fail: 'border-gold/35 text-gold',
  increase_score_on_pass: 'border-brand/35 text-brand',
} as const

export function EffectBadge({ effect, className }: { effect: RuleEffect; className?: string }) {
  const { t } = useTranslation('strategies')
  const Icon = ICON[effect]
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[0.6875rem] font-medium', TONE[effect], className)}>
      <Icon aria-hidden className="size-3" />
      {t(`effect.${effect}`)}
    </span>
  )
}
