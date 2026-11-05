import { directionOf, PRICE_TONE } from '@/shared/lib/direction'
import { cn } from '@/shared/lib/utils'
import { ChangeValue } from './change-value'

interface QuoteHeadlineProps {
  /** The level or price, already formatted. */
  value: string
  /** Against the session before; null when the history has one session. */
  change: number | null
  changeRatio: number | null
  /** The session the value closed, such as "11/3 close". */
  asOf: string
  className?: string
}

/** A page's hero number: the close in its market color, the change with its sign and arrow, and its session. */
export function QuoteHeadline({ value, change, changeRatio, asOf, className }: QuoteHeadlineProps) {
  return (
    <div className={cn('flex flex-wrap items-baseline gap-x-3 gap-y-1.5', className)}>
      <span className={cn('figure', PRICE_TONE[directionOf(change ?? 0)])}>{value}</span>
      {change !== null && changeRatio !== null && (
        <span className="flex items-center gap-2 text-base">
          <ChangeValue value={change} format="absolute" arrow />
          <ChangeValue value={changeRatio} format="percent" pill />
        </span>
      )}
      <span className="w-full text-xs text-muted-foreground sm:w-auto">{asOf}</span>
    </div>
  )
}
