import { cn } from '@/shared/lib/utils'

interface RangeMeterProps {
  low: number
  high: number
  value: number
  lowLabel: string
  highLabel: string
  format: (value: number) => string
  className?: string
}

/** Where a value sits between a low and a high, such as a close inside its one-year range. */
export function RangeMeter({ low, high, value, lowLabel, highLabel, format, className }: RangeMeterProps) {
  const position = high > low ? Math.min(1, Math.max(0, (value - low) / (high - low))) : 0.5
  return (
    <div className={cn('space-y-2', className)}>
      <div aria-hidden className="relative h-2 rounded-full bg-muted">
        <span
          className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card bg-foreground shadow-card"
          style={{ left: `${position * 100}%` }}
        />
      </div>
      <dl className="flex justify-between gap-4 text-xs">
        <div>
          <dt className="text-muted-foreground">{lowLabel}</dt>
          <dd className="tabular font-medium">{format(low)}</dd>
        </div>
        <div className="text-right">
          <dt className="text-muted-foreground">{highLabel}</dt>
          <dd className="tabular font-medium">{format(high)}</dd>
        </div>
      </dl>
    </div>
  )
}
