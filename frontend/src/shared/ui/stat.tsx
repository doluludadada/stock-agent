import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

interface StatProps {
  label: ReactNode
  children: ReactNode
  /** A summary figure reads larger than a figure in a row of details. */
  size?: 'md' | 'lg'
  className?: string
}

/** A label over a figure, for a row of figures inside a `<dl>`. */
export function Stat({ label, children, size = 'md', className }: StatProps) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className="truncate text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('tabular mt-0.5 font-medium', size === 'lg' ? 'text-figure-sm font-semibold' : 'text-sm')}>{children}</dd>
    </div>
  )
}
