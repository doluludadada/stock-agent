import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/utils'

interface StateBlockProps {
  icon: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  tone?: 'neutral' | 'danger'
  className?: string
}

/** Empty, signed-out, error and not-found states share one compact layout; inside a card it needs no frame of its own. */
export function StateBlock({ icon: Icon, title, description, action, tone = 'neutral', className }: StateBlockProps) {
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex flex-col items-center justify-center gap-3 px-4 py-8 text-center', className)}>
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
