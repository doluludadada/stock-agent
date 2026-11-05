import { useId, type ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

interface PanelProps {
  title?: ReactNode
  /** One line under the title: the question the card answers, or the session it describes. */
  description?: ReactNode
  /** The right side of the title row: a date, a count, tabs or actions. */
  aside?: ReactNode
  /** Under the content, behind a hairline: a show-more toggle or a link to the full page. */
  footer?: ReactNode
  /** The footer's own classes, such as hiding it where the list already shows every row. */
  footerClassName?: string
  children: ReactNode
  /** Tables and lists run edge to edge; everything else gets the body padding. */
  flush?: boolean
  className?: string
}

/**
 * The one card every page uses: a title row, its content, and an optional footer. The body is a size container, so
 * what is inside lays out by the card's width (`@md:`), not the window's: the same card works in a side column and
 * at full width.
 */
export function Panel({ title, description, aside, footer, footerClassName, children, flush = false, className }: PanelProps) {
  const id = useId()
  const header = Boolean(title || aside)
  return (
    <section aria-labelledby={title ? id : undefined} className={cn('flex min-w-0 flex-col rounded-2xl border bg-card shadow-card', className)}>
      {header && (
        <header className={cn('flex flex-wrap items-start justify-between gap-x-3 gap-y-2 px-4 pt-3.5 md:px-5 md:pt-4', flush ? 'pb-3' : 'pb-1')}>
          {title && (
            <div className="min-w-0">
              <h2 id={id} className="flex items-center gap-2 text-title font-semibold">
                {title}
              </h2>
              {description && <p className="mt-0.5 text-xs text-pretty text-muted-foreground">{description}</p>}
            </div>
          )}
          {aside && <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">{aside}</div>}
        </header>
      )}
      <div className={cn('@container flex-1', flush ? header && 'border-t' : cn('px-4 pb-4 md:px-5 md:pb-5', header ? 'pt-3' : 'pt-4 md:pt-5'))}>{children}</div>
      {footer && <div className={cn('border-t p-1.5', footerClassName)}>{footer}</div>}
    </section>
  )
}
