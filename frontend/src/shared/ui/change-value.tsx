import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import { useLocale, useTranslation } from '@/i18n'
import { formatSigned, formatSignedPercent } from '@/shared/lib/format'
import { directionOf, type Direction } from '@/shared/lib/direction'
import { cn } from '@/shared/lib/utils'

/** Taiwan convention: red rises, green falls. The sign, arrow and hidden word carry it too. */
const directionText: Record<Direction, string> = {
  up: 'text-up',
  down: 'text-down',
  flat: 'text-flat',
}

interface ChangeValueProps {
  value: number
  format: 'percent' | 'absolute'
  fractionDigits?: number
  arrow?: boolean
  pill?: boolean
  className?: string
}

export function ChangeValue({ value, format, fractionDigits = 2, arrow = false, pill = false, className }: ChangeValueProps) {
  const locale = useLocale()
  const { t } = useTranslation()
  const direction = directionOf(value)
  const Icon = direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : Minus
  const text = format === 'percent' ? formatSignedPercent(locale, value, fractionDigits) : formatSigned(locale, value, fractionDigits)
  return (
    <span
      className={cn(
        'tabular inline-flex items-center gap-0.5 font-medium whitespace-nowrap',
        directionText[direction],
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
