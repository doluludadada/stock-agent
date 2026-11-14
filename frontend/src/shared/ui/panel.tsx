import { ArrowRight, ChevronDown } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { cn } from '@/shared/lib/utils'

/** Where a folding card starts closed: everywhere, or only where the page is one column (under 768 px). */
export type PanelFold = 'always' | 'phone'

interface PanelProps {
  title?: ReactNode
  /** One short line under the title, only where the title alone does not say what the card holds. */
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
  /** The title becomes the button that opens the card. Its content mounts when it opens, so a closed card asks nothing. */
  fold?: PanelFold
  className?: string
}

const PHONE = '(max-width: 47.99rem)'

function startsOpen(fold: PanelFold | undefined): boolean {
  if (fold === undefined) return true
  return fold === 'phone' && !(typeof window.matchMedia === 'function' && window.matchMedia(PHONE).matches)
}

/** A card's way to the page that holds the whole of what it shows, for the right side of its title row. */
export function PanelLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="tap -my-3 gap-1 rounded-md text-sm font-medium text-brand underline-offset-4 hover:underline md:my-0">
      {children}
      <ArrowRight aria-hidden className="size-3.5 shrink-0" />
    </Link>
  )
}

/**
 * The one card every page uses: a title row, its content, and an optional footer. The body is a size container, so
 * what is inside lays out by the card's width (`@md:`), not the window's.
 */
export function Panel({ title, description, aside, footer, footerClassName, children, flush = false, fold, className }: PanelProps) {
  const id = useId()
  const bodyId = useId()
  const [open, setOpen] = useState(() => startsOpen(fold))
  const header = Boolean(title || aside)
  return (
    <section aria-labelledby={title ? id : undefined} className={cn('flex min-w-0 flex-col rounded-2xl border bg-card shadow-card', className)}>
      {header && (
        <header className={cn('flex flex-wrap items-start justify-between gap-x-3 gap-y-2 px-4 pt-3.5 md:px-5 md:pt-4', !open ? 'pb-3.5 md:pb-4' : flush ? 'pb-3' : 'pb-1')}>
          {title && (
            <div className={cn('min-w-0', fold && 'flex-1')}>
              <h2 id={id} className="flex items-center gap-2 text-title font-semibold">
                {fold ? (
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={bodyId}
                    onClick={() => setOpen(!open)}
                    className="-my-3 flex min-h-11 w-full items-center justify-between gap-2 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="flex min-w-0 items-center gap-2">{title}</span>
                    <ChevronDown aria-hidden className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
                  </button>
                ) : (
                  title
                )}
              </h2>
              {description && open && <p className="mt-0.5 text-xs text-pretty text-muted-foreground">{description}</p>}
            </div>
          )}
          {aside && open && <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">{aside}</div>}
        </header>
      )}
      {open && (
        <>
          <div id={bodyId} className={cn('@container flex-1', flush ? header && 'border-t' : cn('px-4 pb-4 md:px-5 md:pb-5', header ? 'pt-3' : 'pt-4 md:pt-5'))}>
            {children}
          </div>
          {footer && <div className={cn('border-t p-1.5', footerClassName)}>{footer}</div>}
        </>
      )}
    </section>
  )
}
