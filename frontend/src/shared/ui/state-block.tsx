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

/** Empty, locked, error and not-found states share one compact layout; inside a panel it needs no frame of its own. */
export function StateBlock({ icon: Icon, title, description, action, tone = 'neutral', className }: StateBlockProps) {
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex flex-col items-center justify-center gap-2 px-4 py-6 text-center', className)}>
      <Icon aria-hidden className={cn('size-5', tone === 'danger' ? 'text-destructive' : 'text-muted-foreground')} />
      <div className="max-w-sm space-y-0.5">
        <p className="text-sm font-medium">{title}</p>
        {description && <p className="text-xs text-pretty text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  )
}
