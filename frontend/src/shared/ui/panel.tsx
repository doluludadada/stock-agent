import { useId, type ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

interface PanelProps {
  title?: ReactNode
  /** The right side of the title bar: a date, a count, tabs or actions. */
  aside?: ReactNode
  children: ReactNode
  /** Tables and lists run edge to edge; everything else gets the body padding. */
  flush?: boolean
  className?: string
}

/** The one bordered block every page uses: an optional title bar over its content. */
export function Panel({ title, aside, children, flush = false, className }: PanelProps) {
  const id = useId()
  return (
    <section aria-labelledby={title ? id : undefined} className={cn('min-w-0 rounded-xl border bg-card shadow-card', className)}>
      {(title || aside) && (
        <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-b px-4 py-2">
          {title && (
            <h2 id={id} className="flex items-center gap-2 text-sm font-semibold">
              {title}
            </h2>
          )}
          {aside && <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">{aside}</div>}
        </div>
      )}
      <div className={flush ? undefined : 'p-4'}>{children}</div>
    </section>
  )
}
