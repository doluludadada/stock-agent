import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

interface StateBlockProps {
  icon: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  tone?: 'neutral' | 'danger'
  /** Alone on a page, the state is its own card; inside a card it needs no frame. */
  framed?: boolean
  className?: string
}

/** Empty, signed-out, refused, error and not-found states share one compact layout, framed as a card where they stand alone. */
export function StateBlock({ icon: Icon, title, description, action, tone = 'neutral', framed = false, className }: StateBlockProps) {
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex flex-col items-center justify-center gap-3 px-4 py-8 text-center', framed && 'rounded-2xl border bg-card py-12 shadow-card', className)}>
      <span className={cn('grid size-10 place-items-center rounded-full', tone === 'danger' ? 'bg-danger-soft text-destructive' : 'bg-muted text-muted-foreground')}>
        <Icon aria-hidden className="size-5" />
      </span>
      <div className="max-w-sm space-y-1">
        <p className="text-title font-semibold text-balance">{title}</p>
        {description && <p className="text-sm text-pretty text-muted-foreground">{description}</p>}
      </div>
      {action && <div className="flex flex-wrap items-center justify-center gap-2">{action}</div>}
    </div>
  )
}
