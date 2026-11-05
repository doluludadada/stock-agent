import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

/** A label over a figure, for a row of figures inside a `<dl>`. */
export function Stat({ label, children, className }: { label: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className="truncate text-xs text-muted-foreground">{label}</dt>
      <dd className="tabular mt-0.5 text-sm font-medium">{children}</dd>
    </div>
  )
}
