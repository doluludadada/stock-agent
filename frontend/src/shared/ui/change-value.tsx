import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import { useTranslation } from '@/i18n'
import { useFormat } from '@/shared/lib/format'
import { DIRECTION_TONE, directionOf } from '@/shared/lib/direction'
import { cn } from '@/shared/lib/utils'

interface ChangeValueProps {
  value: number
  format: 'percent' | 'absolute'
  fractionDigits?: number
  arrow?: boolean
  pill?: boolean
  className?: string
}

export function ChangeValue({ value, format, fractionDigits = 2, arrow = false, pill = false, className }: ChangeValueProps) {
  const numbers = useFormat()
  const { t } = useTranslation()
  const direction = directionOf(value)
  const Icon = direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : Minus
  const text = format === 'percent' ? numbers.signedPercent(value, fractionDigits) : numbers.signed(value, fractionDigits)
  return (
    <span
      className={cn(
        'tabular inline-flex items-center gap-0.5 font-medium whitespace-nowrap',
        DIRECTION_TONE[direction].text,
        pill && 'rounded-full px-2 py-0.5 text-xs',
        pill && direction === 'up' && 'bg-up-soft',
        pill && direction === 'down' && 'bg-down-soft',
        pill && direction === 'flat' && 'bg-muted',
        className,
      )}
    >
      {arrow && <Icon aria-hidden className="size-3.5 shrink-0" />}
      <span className="sr-only">{t(`direction.${direction}`)} </span>
      {text}
    </span>
  )
}
