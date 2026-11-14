import { createContext, useContext, type ReactNode } from 'react'
import { usePageTitle } from '@/shared/lib/page-title'
import { cn } from '@/shared/lib/utils'

/**
 * The name of the navigation section the page on screen belongs to. The shell provides it from the one list of pages,
 * so no page names its own section and none can name the wrong one.
 */
const PageSectionContext = createContext<string | null>(null)
export const PageSectionProvider = PageSectionContext.Provider

interface PageHeaderProps {
  title: ReactNode
  /** The browser tab's name where `title` is not plain text, such as a stock's name beside its code. */
  tabTitle?: string
  /** One short line under the title. */
  description?: ReactNode
  actions?: ReactNode
  className?: string
}

/** The top of every page: its section, its one title, one line about it, and its actions. It names the browser tab too. */
export function PageHeader({ title, tabTitle, description, actions, className }: PageHeaderProps) {
  const eyebrow = useContext(PageSectionContext)
  usePageTitle(tabTitle ?? (typeof title === 'string' ? title : null))
  return (
    <header className={cn('flex flex-wrap items-end justify-between gap-x-4 gap-y-3', className)}>
      <div className="min-w-0 space-y-1">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1 className="display text-balance">{title}</h1>
        {description && <p className="text-sm text-pretty text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
